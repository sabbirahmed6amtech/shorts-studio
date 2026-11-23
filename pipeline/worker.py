"""Two background threads.

- The video lane runs jobs in order: download -> audio -> transcribe -> Gemini.
  Each stage skips itself if its output already exists, so a job interrupted by
  closing the app resumes where it stopped.
- The output lane renders clips and uploads them to YouTube, so a long transcription
  never holds up a render.
"""
from datetime import datetime, timezone
import json
import queue
import threading
import time
import traceback

from . import ai, config, tools, youtube
from .download import download
from .render import render, render_sig
from .transcribe import transcribe

_q: "queue.Queue[tuple[int, str]]" = queue.Queue()      # video lane
_out_q: "queue.Queue[tuple[int, str]]" = queue.Queue()  # output lane: (clip id, 'render' | 'upload')
_queued: set[tuple[int, str]] = set()
_qlock = threading.Lock()
BUSY = ("queued", "downloading", "transcribing", "analyzing")


def enqueue(job_id: int, kind: str = "process") -> None:
    with _qlock:
        if (job_id, kind) in _queued:
            return
        _queued.add((job_id, kind))
    _q.put((job_id, kind))


def enqueue_output(clip_id: int, kind: str) -> None:
    key = (clip_id, f"out:{kind}")
    with _qlock:
        if key in _queued:
            return
        _queued.add(key)
    _out_q.put((clip_id, kind))


def start() -> None:
    with config.db() as c:
        rows = c.execute(f"SELECT id FROM jobs WHERE status IN ({','.join('?' * len(BUSY))}) ORDER BY id",
                         BUSY).fetchall()
        clips = c.execute("SELECT id, render_status, yt_status FROM clips WHERE render_status IN "
                          "('queued','rendering') OR yt_status IN ('queued','uploading') ORDER BY id").fetchall()
    for r in rows:
        config.update_job(r["id"], status="queued", progress=0)
        enqueue(r["id"])
    for r in clips:  # resume renders/uploads the app was closed in the middle of
        if r["yt_status"] in ("queued", "uploading"):
            config.update_clip(r["id"], yt_status="queued", yt_progress=0)
            enqueue_output(r["id"], "upload")
        else:
            config.update_clip(r["id"], render_status="queued", render_progress=0)
            enqueue_output(r["id"], "render")
    threading.Thread(target=_loop, name="worker", daemon=True).start()
    threading.Thread(target=_out_loop, name="output-worker", daemon=True).start()


def _loop() -> None:
    while True:
        job_id, kind = _q.get()
        with _qlock:
            _queued.discard((job_id, kind))
        try:
            if config.get_job(job_id) is None:
                continue  # deleted while waiting
            if kind == "process":
                _process(job_id)
            elif kind == "analyze":
                _analyze(job_id)
        except Exception as e:
            traceback.print_exc()
            config.update_job(job_id, status="error", message=str(e)[:500])


def _out_loop() -> None:
    while True:
        clip_id, kind = _out_q.get()
        with _qlock:
            _queued.discard((clip_id, f"out:{kind}"))
        clip = config.get_clip(clip_id)
        if clip is None:
            continue  # deleted while waiting
        try:
            if kind == "render":
                if clip["render_status"] != "queued":
                    continue  # cancelled
                _render(clip)
            elif kind == "upload":
                if clip["yt_status"] != "queued":
                    continue  # cancelled
                _upload(clip)
        except Exception as e:
            traceback.print_exc()
            msg = str(e)[:500]
            if kind == "render":
                config.update_clip(clip_id, render_status="error", render_error=msg)
            else:
                config.update_clip(clip_id, yt_status="error", yt_error=msg)


class _Throttle:
    """Write progress to the database at most twice a second."""

    def __init__(self, row_id, field="progress", update=None):
        self.row_id, self.field, self.last = row_id, field, 0.0
        self.update = update or config.update_job

    def __call__(self, p: float):
        now = time.monotonic()
        if now - self.last > 0.5 or p >= 1:
            self.last = now
            self.update(self.row_id, **{self.field: round(p, 3)})


def render_is_current(clip: dict, settings: dict | None = None) -> bool:
    if clip.get("render_status") != "done" or not clip.get("render_file"):
        return False
    if not (config.job_dir(clip["job_id"]) / "clips" / clip["render_file"]).exists():
        return False
    return clip.get("render_sig") == render_sig(clip, settings or config.get_settings())


def _render(clip: dict) -> dict:
    s = config.get_settings()
    job = config.get_job(clip["job_id"])
    config.update_clip(clip["id"], render_status="rendering", render_progress=0, render_error=None)
    sig = render_sig(clip, s)
    out = render(clip, job, s, _Throttle(clip["id"], "render_progress", config.update_clip))
    old = clip.get("render_file")
    config.update_clip(clip["id"], render_status="done", render_progress=1, render_file=out.name,
                       render_sig=sig, rendered_at=config.now_iso())
    if old and old != out.name:  # tidy up the previous render; ignore if it's still open somewhere
        try:
            (out.parent / old).unlink(missing_ok=True)
        except OSError:
            pass
    return config.get_clip(clip["id"])


def _upload(clip: dict) -> None:
    s = config.get_settings()
    job = config.get_job(clip["job_id"])
    config.update_clip(clip["id"], yt_status="uploading", yt_progress=0, yt_error=None)
    if not render_is_current(clip, s):  # render (or re-render) first, then upload
        config.update_clip(clip["id"], render_status="queued")
        try:
            clip = _render(config.get_clip(clip["id"]))
        except Exception as e:
            config.update_clip(clip["id"], render_status="error", render_error=str(e)[:500])
            raise RuntimeError(f"Rendering failed, so nothing was uploaded: {e}")
    path = config.job_dir(clip["job_id"]) / "clips" / clip["render_file"]
    video_id = youtube.upload(path, clip, job, s, _Throttle(clip["id"], "yt_progress", config.update_clip))
    scheduled = bool(clip.get("yt_publish_at")) and \
        datetime.fromisoformat(clip["yt_publish_at"].replace("Z", "+00:00")) > datetime.now(timezone.utc)
    config.update_clip(clip["id"], yt_status="scheduled" if scheduled else "published", yt_progress=1,
                       yt_video_id=video_id, yt_uploaded_at=config.now_iso())


def _process(job_id: int) -> None:
    if not tools.health()["ready"]:
        raise RuntimeError("ffmpeg is not installed. See the setup checks on the home page.")
    job = config.get_job(job_id)
    d = config.job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)

    # 1. Download
    video = d / job["video_file"] if job["video_file"] else None
    if not video or not video.exists():
        if job["source"] != "url":
            raise RuntimeError("The uploaded file is missing. Delete this job and upload again.")
        config.update_job(job_id, status="downloading", progress=0, message=None)
        video, title = download(job["url"], d, _Throttle(job_id))
        config.update_job(job_id, video_file=video.name, title=job["title"] or title)

    # 2. Probe + audio + waveform
    config.update_job(job_id, status="transcribing", progress=0, message=None)
    meta = tools.probe(video)
    warn = None
    if meta["vcodec"] not in ("h264", "vp9", "av1"):
        warn = f"This video uses the {meta['vcodec']} codec, which some browsers can't preview."
    config.update_job(job_id, duration=meta["duration"], video_codec=meta["vcodec"], message=warn)
    wav, peaks = d / "audio.wav", d / "peaks.json"
    if not wav.exists():
        tools.extract_audio(video, wav)
    if not peaks.exists():
        tools.compute_peaks(wav, peaks)

    # 3. Transcribe
    tr = d / "transcript.json"
    if not tr.exists():
        transcribe(wav, tr, config.get_settings(), _Throttle(job_id))

    # 4. Gemini
    _analyze(job_id)


def _analyze(job_id: int) -> None:
    job = config.get_job(job_id)
    tr = config.job_dir(job_id) / "transcript.json"
    if not tr.exists():
        raise RuntimeError("No transcript yet.")
    config.update_job(job_id, status="analyzing", progress=0, ai_error=None)
    data = json.loads(tr.read_text(encoding="utf-8"))
    s = config.get_settings()
    try:
        suggestions = ai.suggest(data["lines"], s)
        tags = [t if t.startswith("#") else f"#{t}" for t in s["default_hashtags"].split()]
        clips = ai.to_clips(suggestions, data["lines"], s, job["duration"] or data["duration"], tags)
    except ai.AIError as e:
        # The video is still usable: open the editor and pick clips by hand.
        config.update_job(job_id, status="ready", progress=1, ai_error=str(e))
        return
    with config.db() as c:
        c.execute("DELETE FROM clips WHERE job_id = ? AND origin = 'ai' AND edited = 0", (job_id,))
        for cl in clips:
            c.execute(
                "INSERT INTO clips(job_id, start, end, score, title, description, hashtags, hook, reason, origin, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?, 'ai', ?)",
                (job_id, cl["start"], cl["end"], cl["score"], cl["title"], cl["description"],
                 json.dumps(cl["hashtags"], ensure_ascii=False), cl["hook"], cl["reason"], config.now_iso()),
            )
    note = None if clips else "Gemini found no clips that fit your length settings. Try a wider range in Settings."
    config.update_job(job_id, status="ready", progress=1, ai_error=note)

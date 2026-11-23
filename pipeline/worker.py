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

from . import ai, captions, chat, config, facebook, loudness, tools, youtube
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
        clips = c.execute("SELECT id, render_status, yt_status, fb_status FROM clips WHERE render_status IN "
                          "('queued','rendering') OR yt_status IN ('queued','uploading') "
                          "OR fb_status IN ('queued','uploading') ORDER BY id").fetchall()
    for r in rows:
        config.update_job(r["id"], status="queued", progress=0)
        enqueue(r["id"])
    for r in clips:  # resume renders/uploads the app was closed in the middle of
        busy_upload = False
        if r["yt_status"] in ("queued", "uploading"):
            config.update_clip(r["id"], yt_status="queued", yt_progress=0)
            enqueue_output(r["id"], "upload")
            busy_upload = True
        if r["fb_status"] in ("queued", "uploading"):
            config.update_clip(r["id"], fb_status="queued", fb_progress=0)
            enqueue_output(r["id"], "fb_upload")
            busy_upload = True
        if not busy_upload:
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
            elif kind == "fb_upload":
                if clip["fb_status"] != "queued":
                    continue  # cancelled
                _fb_upload(clip)
        except Exception as e:
            traceback.print_exc()
            msg = str(e)[:500]
            if kind == "render":
                config.update_clip(clip_id, render_status="error", render_error=msg)
            elif kind == "fb_upload":
                config.update_clip(clip_id, fb_status="error", fb_error=msg)
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


def render_is_current(clip: dict, settings: dict | None = None, job: dict | None = None) -> bool:
    if clip.get("render_status") != "done" or not clip.get("render_file"):
        return False
    if not (config.job_dir(clip["job_id"]) / "clips" / clip["render_file"]).exists():
        return False
    return clip.get("render_sig") == render_sig(clip, settings or config.get_settings(), job)


def _render(clip: dict) -> dict:
    s = config.get_settings()
    job = config.get_job(clip["job_id"])
    config.update_clip(clip["id"], render_status="rendering", render_progress=0, render_error=None)
    sig = render_sig(clip, s, job)
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


def _ensure_render(clip: dict, s: dict) -> dict:
    """Render (or re-render) first if the file is missing or out of date."""
    if render_is_current(clip, s):
        return clip
    config.update_clip(clip["id"], render_status="queued")
    try:
        return _render(config.get_clip(clip["id"]))
    except Exception as e:
        config.update_clip(clip["id"], render_status="error", render_error=str(e)[:500])
        raise RuntimeError(f"Rendering failed, so nothing was uploaded: {e}")


def _fb_upload(clip: dict) -> None:
    job = config.get_job(clip["job_id"])
    config.update_clip(clip["id"], fb_status="uploading", fb_progress=0, fb_error=None)
    facebook.check_length(clip["end"] - clip["start"])  # fail before spending time on a render
    clip = _ensure_render(clip, config.get_settings())
    path = config.job_dir(clip["job_id"]) / "clips" / clip["render_file"]
    video_id = facebook.upload(path, clip, job, _Throttle(clip["id"], "fb_progress", config.update_clip))
    scheduled = bool(clip.get("fb_publish_at"))
    config.update_clip(clip["id"], fb_status="scheduled" if scheduled else "published", fb_progress=1,
                       fb_video_id=video_id, fb_uploaded_at=config.now_iso())


def _upload(clip: dict) -> None:
    s = config.get_settings()
    job = config.get_job(clip["job_id"])
    config.update_clip(clip["id"], yt_status="uploading", yt_progress=0, yt_error=None)
    clip = _ensure_render(clip, s)
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
        _make_transcript(job, d, wav, meta["duration"], tr, job_id)

    # 3b. Live chat replay (past streams only). Never fails the job.
    if job["source"] == "url" and config.get_settings()["chat_hints"] and not (d / "chat.json").exists():
        _fetch_chat(job, d, meta["duration"], job_id)

    # 4. Gemini
    _analyze(job_id)


def _make_transcript(job: dict, d, wav, duration: float, tr, job_id: int) -> None:
    """YouTube captions, Whisper or nothing, depending on Settings → Transcript source."""
    s = config.get_settings()
    mode = s["transcript_source"]
    note = None
    if mode in ("auto", "youtube") and job["source"] == "url":
        sub = next(iter(sorted(d.glob("captions*.json3"))), None)
        if sub is None:
            sub, note = captions.fetch(job["url"], d, s["language"])
        if sub is not None:
            data = captions.parse(sub, duration)
            if data["words"]:
                tr.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                config.update_job(job_id, transcript_source="youtube")
                return
            note = "The YouTube captions were empty."
    if mode in ("auto", "whisper"):
        if note:
            config.update_job(job_id, message=f"{note} Transcribing with Whisper instead.")
        transcribe(wav, tr, s, _Throttle(job_id))
        config.update_job(job_id, transcript_source="whisper", message=None)
        return
    # 'none', or 'youtube' without captions: no speech; loudness hints can still guide Gemini.
    tr.write_text(json.dumps({"language": "", "duration": duration, "words": [], "lines": [], "source": "none"}),
                  encoding="utf-8")
    config.update_job(job_id, transcript_source="none", message=note if mode == "youtube" else None)


def _fetch_chat(job: dict, d, duration: float, job_id: int) -> None:
    config.update_job(job_id, status="transcribing", progress=0, message="Reading the live chat replay…")
    try:
        raw, note = chat.fetch(job["url"], d)
        if raw:
            data = chat.parse(raw, d / "chat.json", duration)
        else:
            # Remember there's no chat, so a resumed job doesn't ask again.
            data = {"per_second": [], "samples": {}, "total": 0}
            (d / "chat.json").write_text(json.dumps(data), encoding="utf-8")
        config.update_job(job_id, chat_messages=data["total"], message=note or None)
    except Exception as e:
        traceback.print_exc()
        config.update_job(job_id, message=f"Skipped the live chat: {str(e)[:150]}")


def analysis_lines(job_id: int, s: dict) -> tuple[list[dict], float]:
    """The numbered lines the AI reads: transcript plus loudness / chat markers. Shared by the
    Gemini call and the copy-paste prompt for other AI tools, so both see exactly the same."""
    job = config.get_job(job_id)
    tr = config.job_dir(job_id) / "transcript.json"
    if not tr.exists():
        raise RuntimeError("No transcript yet.")
    data = json.loads(tr.read_text(encoding="utf-8"))
    duration = job["duration"] or data["duration"]
    lines = data["lines"]
    wav = config.job_dir(job_id) / "audio.wav"
    chat_file = config.job_dir(job_id) / "chat.json"
    measure = None
    if s["chat_hints"] and chat_file.exists():
        measure = chat.spikes(json.loads(chat_file.read_text(encoding="utf-8")))
    use_wav = wav if s["loudness_hints"] and wav.exists() else None
    if use_wav or measure:
        lines = loudness.annotate(lines, use_wav, duration, chat=measure)
    return lines, duration


def default_tags(s: dict) -> list[str]:
    return [t if t.startswith("#") else f"#{t}" for t in s["default_hashtags"].split()]


def save_ai_clips(job_id: int, clips: list[dict]) -> None:
    """Replace AI clips the user hasn't touched; keep clips they made or edited."""
    with config.db() as c:
        c.execute("DELETE FROM clips WHERE job_id = ? AND origin = 'ai' AND edited = 0", (job_id,))
        for cl in clips:
            c.execute(
                "INSERT INTO clips(job_id, start, end, score, title, description, hashtags, hook, reason, hook_title,"
                " origin, created_at) VALUES (?,?,?,?,?,?,?,?,?,?, 'ai', ?)",
                (job_id, cl["start"], cl["end"], cl["score"], cl["title"], cl["description"],
                 json.dumps(cl["hashtags"], ensure_ascii=False), cl["hook"], cl["reason"], cl["hook_title"],
                 config.now_iso()),
            )


def _analyze(job_id: int) -> None:
    job = config.get_job(job_id)
    config.update_job(job_id, status="analyzing", progress=0, ai_error=None)
    s = config.get_settings()
    lines, duration = analysis_lines(job_id, s)
    try:
        suggestions = ai.suggest(lines, s, job["title"] or "")
        clips = ai.to_clips(suggestions, lines, s, duration, default_tags(s))
    except ai.AIError as e:
        # The video is still usable: open the editor and pick clips by hand.
        config.update_job(job_id, status="ready", progress=1, ai_error=str(e))
        return
    save_ai_clips(job_id, clips)
    note = None if clips else "Gemini found no clips that fit your length settings. Try a wider range in Settings."
    config.update_job(job_id, status="ready", progress=1, ai_error=note)

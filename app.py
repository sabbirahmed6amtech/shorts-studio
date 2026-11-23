"""Shorts Studio: turn long videos into YouTube Shorts, locally.

Run with start.bat (Windows) or ./start.sh (Mac/Linux), or: python app.py
"""
import json
import mimetypes
import os
import shutil
import threading
import webbrowser
from contextlib import asynccontextmanager

# Windows can map .js to text/plain through the registry, and browsers then refuse
# to run module scripts. Set the types explicitly before anything serves files.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")

from datetime import datetime, timedelta, timezone  # noqa: E402

from fastapi import FastAPI, File, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from pipeline import ai, config, facebook, tools, worker, youtube  # noqa: E402

HOST = "127.0.0.1"  # local only: the app holds your API keys and has no login
PORT = int(os.environ.get("PORT", "8000"))
VIDEO_TYPES = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
ACTIVE = ("downloading", "transcribing", "analyzing")
CLIP_BUSY_SQL = ("(render_status IN ('queued','rendering') OR yt_status IN ('queued','uploading') "
                 "OR fb_status IN ('queued','uploading'))")

config.init_db()


@asynccontextmanager
async def lifespan(_app):
    worker.start()
    yield


app = FastAPI(title="Shorts Studio", lifespan=lifespan)


def _job_or_404(job_id: int) -> dict:
    job = config.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


# ---------- setup + settings ----------

@app.get("/api/health")
def health():
    return tools.health()


@app.get("/api/settings")
def get_settings():
    s = config.get_settings()
    key = s.pop("gemini_api_key")
    s["gemini_key_set"] = bool(key)
    s["gemini_key_hint"] = f"…{key[-4:]}" if len(key) > 8 else ""
    return s


@app.put("/api/settings")
def put_settings(values: dict):
    values = dict(values)
    if not values.get("gemini_api_key"):
        values.pop("gemini_api_key", None)  # blank field = keep the saved key
    if values.get("clear_gemini_key"):
        values["gemini_api_key"] = ""
    current = config.get_settings()
    try:
        nums = {k: int(float(values.get(k, current[k])))
                for k in ("clip_min", "clip_max", "clip_count", "min_score")}
    except (TypeError, ValueError):
        raise HTTPException(400, "A number field has an invalid value.")
    if nums["clip_min"] < 5 or nums["clip_max"] <= nums["clip_min"]:
        raise HTTPException(400, "Clip length: minimum must be at least 5s and below the maximum.")
    if not 1 <= nums["clip_count"] <= 30 or not 0 <= nums["min_score"] <= 100:
        raise HTTPException(400, "Clips per video must be 1–30 and minimum score 0–100.")
    if values.get("whisper_device") not in (None, "cpu", "cuda", "mps"):
        raise HTTPException(400, "Unknown device.")
    config.save_settings(values)
    tools.reset_cache()
    return get_settings()


# ---------- jobs ----------

class NewJob(BaseModel):
    url: str


@app.get("/api/jobs")
def list_jobs():
    with config.db() as c:
        rows = c.execute(
            "SELECT j.*, (SELECT COUNT(*) FROM clips WHERE job_id = j.id) AS clip_count "
            "FROM jobs j ORDER BY j.id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/jobs")
def create_job(body: NewJob):
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Paste a full link starting with https://")
    with config.db() as c:
        cur = c.execute("INSERT INTO jobs(source, url, status, created_at) VALUES('url', ?, 'queued', ?)",
                        (url, config.now_iso()))
        job_id = cur.lastrowid
    _apply_default_layout(job_id)
    worker.enqueue(job_id)
    return config.get_job(job_id)


@app.post("/api/jobs/upload")
def upload_job(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in VIDEO_TYPES:
        raise HTTPException(400, f"Unsupported file type. Use one of: {', '.join(sorted(VIDEO_TYPES))}")
    title = os.path.splitext(os.path.basename(file.filename))[0][:200]
    with config.db() as c:
        cur = c.execute("INSERT INTO jobs(source, title, status, video_file, created_at) "
                        "VALUES('upload', ?, 'queued', ?, ?)", (title, f"source{ext}", config.now_iso()))
        job_id = cur.lastrowid
    _apply_default_layout(job_id)
    d = config.job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"source{ext}", "wb") as out:
        shutil.copyfileobj(file.file, out, length=1024 * 1024)
    worker.enqueue(job_id)
    return config.get_job(job_id)


def _apply_default_layout(job_id: int) -> None:
    raw = config.get_settings().get("layout_default")
    if raw:
        d = json.loads(raw)
        config.update_job(job_id, layout=d.get("mode", "single"), layout_json=json.dumps(d.get("data")) if d.get("data") else None)


class Rect(BaseModel):
    x: float
    y: float
    w: float
    h: float


class LayoutIn(BaseModel):
    mode: str                      # 'single' | 'split'
    split: float = 0.4             # share of the height the streamer part takes
    cam: Rect | None = None
    content: Rect | None = None


@app.put("/api/jobs/{job_id}/layout")
def set_layout(job_id: int, body: LayoutIn):
    _job_or_404(job_id)
    if body.mode not in ("single", "split"):
        raise HTTPException(400, "Unknown layout.")
    data = None
    if body.mode == "split":
        if not body.cam or not body.content:
            raise HTTPException(400, "Place both the streamer and the content box.")
        for r in (body.cam, body.content):
            if r.w <= 0.01 or r.h <= 0.01 or r.x < -0.01 or r.y < -0.01 or r.x + r.w > 1.01 or r.y + r.h > 1.01:
                raise HTTPException(400, "A box is outside the video.")
        data = {"split": min(0.6, max(0.25, body.split)), "cam": body.cam.model_dump(), "content": body.content.model_dump()}
    else:
        old = config.get_job(job_id)["layout_json"]  # keep the boxes so switching back restores them
        data = json.loads(old) if old else None
    config.update_job(job_id, layout=body.mode, layout_json=json.dumps(data) if data else None)
    config.save_settings({"layout_default": json.dumps({"mode": body.mode, "data": data})})
    return config.get_job(job_id)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int):
    return _job_or_404(job_id)


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: int):
    job = _job_or_404(job_id)
    if job["status"] in ACTIVE:
        raise HTTPException(409, "This job is still processing. Wait for it to finish, then delete it.")
    with config.db() as c:
        if c.execute(f"SELECT 1 FROM clips WHERE job_id = ? AND {CLIP_BUSY_SQL}", (job_id,)).fetchone():
            raise HTTPException(409, "A clip from this video is rendering or uploading. Wait for it to finish.")
    with config.db() as c:
        c.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    shutil.rmtree(config.job_dir(job_id), ignore_errors=True)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: int):
    job = _job_or_404(job_id)
    if job["status"] != "error":
        raise HTTPException(409, "Only failed jobs can be retried.")
    config.update_job(job_id, status="queued", progress=0, message=None)
    worker.enqueue(job_id)
    return config.get_job(job_id)


# ---------- other AI tools (copy the prompt, paste the reply) ----------

@app.get("/api/jobs/{job_id}/prompt")
def job_prompt(job_id: int):
    """The exact prompt Gemini would get, plus reply-format rules, for pasting into any AI tool.
    The numbered lines are saved so the reply's line numbers still match when it's imported."""
    job = _job_or_404(job_id)
    if job["status"] != "ready":
        raise HTTPException(409, "The video must finish processing first.")
    s = config.get_settings()
    lines, duration = worker.analysis_lines(job_id, s)
    if not lines:
        raise HTTPException(400, "No speech was found. Turn on Loudness hints in Settings so there's something to send.")
    prompt = ai.external_prompt(lines, s, job["title"] or "")
    snapshot = {"lines": lines, "duration": duration, "created_at": config.now_iso(),
                "settings": {k: s[k] for k in ("clip_min", "clip_max", "clip_count", "min_score", "default_hashtags")}}
    (config.job_dir(job_id) / "external_prompt.json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    return {"prompt": prompt, "chars": len(prompt), "lines": len(lines)}


class ImportIn(BaseModel):
    text: str


@app.post("/api/jobs/{job_id}/import")
def import_reply(job_id: int, body: ImportIn):
    job = _job_or_404(job_id)
    if job["status"] != "ready":
        raise HTTPException(409, "The video must finish processing first.")
    snap_path = config.job_dir(job_id) / "external_prompt.json"
    if not snap_path.exists():
        raise HTTPException(400, "Copy the prompt first, then paste the AI's reply.")
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    s = {**config.get_settings(), **snap["settings"]}  # judge the reply by the settings it was asked with
    try:
        suggestions, problems = ai.parse_external(body.text)
        clips = ai.to_clips(suggestions, snap["lines"], s, snap["duration"], worker.default_tags(s))
    except ai.AIError as e:
        raise HTTPException(400, str(e))
    if not clips:
        raise HTTPException(400, "The reply was read, but none of its clips fit your length settings "
                                 f"({s['clip_min']}–{s['clip_max']}s) or they overlapped. Nothing was changed.")
    worker.save_ai_clips(job_id, clips)
    config.update_job(job_id, ai_error=None)
    return {"imported": len(clips), "read": len(suggestions), "skipped": problems}


@app.post("/api/jobs/{job_id}/analyze")
def analyze_job(job_id: int):
    job = _job_or_404(job_id)
    if job["status"] != "ready":
        raise HTTPException(409, "The video must finish processing first.")
    config.update_job(job_id, status="analyzing", progress=0, ai_error=None)
    worker.enqueue(job_id, "analyze")
    return config.get_job(job_id)


def _job_file(job_id: int, name: str):
    path = config.job_dir(job_id) / name
    if not path.exists():
        raise HTTPException(404, "Not ready yet")
    return path


@app.get("/api/jobs/{job_id}/video")
def job_video(job_id: int):
    job = _job_or_404(job_id)
    if not job["video_file"]:
        raise HTTPException(404, "Not downloaded yet")
    return FileResponse(_job_file(job_id, job["video_file"]))  # supports Range requests for seeking


@app.get("/api/jobs/{job_id}/peaks")
def job_peaks(job_id: int):
    return FileResponse(_job_file(job_id, "peaks.json"), media_type="application/json")


@app.get("/api/jobs/{job_id}/transcript")
def job_transcript(job_id: int):
    data = json.loads(_job_file(job_id, "transcript.json").read_text(encoding="utf-8"))
    return {"language": data["language"], "words": data["words"]}


# ---------- clips ----------

class ClipIn(BaseModel):
    start: float | None = None
    end: float | None = None
    title: str | None = None
    description: str | None = None
    hashtags: list[str] | None = None
    crop_x: float | None = None
    hook_title: str | None = None


def _out(clip: dict, settings: dict | None = None, job: dict | None = None) -> dict:
    """Add what the UI needs: is the render up to date with the clip's current edits?"""
    clip["render_current"] = worker.render_is_current(clip, settings, job)
    return clip


def _clip_or_404(clip_id: int) -> dict:
    clip = config.get_clip(clip_id)
    if not clip:
        raise HTTPException(404, "Clip not found")
    return _out(clip)


def _check_range(start: float, end: float, duration: float | None):
    if start < 0 or end <= start + 0.5:
        raise HTTPException(400, "A clip must be at least half a second long.")
    if duration and end > duration + 0.5:
        raise HTTPException(400, "The clip ends after the video does.")


@app.get("/api/jobs/{job_id}/clips")
def list_clips(job_id: int):
    job = _job_or_404(job_id)
    with config.db() as c:
        rows = c.execute("SELECT * FROM clips WHERE job_id = ? ORDER BY start", (job_id,)).fetchall()
    s = config.get_settings()
    return [_out(config.clip_row(r), s, job) for r in rows]


@app.post("/api/jobs/{job_id}/clips")
def create_clip(job_id: int, body: ClipIn):
    job = _job_or_404(job_id)
    if body.start is None or body.end is None:
        raise HTTPException(400, "start and end are required")
    _check_range(body.start, body.end, job["duration"])
    tags = [t for t in config.get_settings()["default_hashtags"].split() if t]
    with config.db() as c:
        cur = c.execute(
            "INSERT INTO clips(job_id, start, end, title, hashtags, origin, created_at) VALUES (?,?,?,?,?, 'manual', ?)",
            (job_id, round(body.start, 2), round(body.end, 2), body.title or "",
             json.dumps(tags, ensure_ascii=False), config.now_iso()),
        )
        clip_id = cur.lastrowid
    return _clip_or_404(clip_id)


@app.patch("/api/clips/{clip_id}")
def update_clip(clip_id: int, body: ClipIn):
    clip = _clip_or_404(clip_id)
    job = config.get_job(clip["job_id"])
    fields = body.model_dump(exclude_none=True)
    start, end = fields.get("start", clip["start"]), fields.get("end", clip["end"])
    _check_range(start, end, job["duration"])
    if "crop_x" in fields:
        fields["crop_x"] = min(1.0, max(0.0, fields["crop_x"]))
    if "hashtags" in fields:
        fields["hashtags"] = json.dumps(
            [t if t.startswith("#") else f"#{t}" for t in (x.strip().replace(" ", "") for x in fields["hashtags"]) if t],
            ensure_ascii=False)
    for k in ("start", "end"):
        if k in fields:
            fields[k] = round(fields[k], 2)
    if fields:
        fields["edited"] = 1
        cols = ", ".join(f"{k} = ?" for k in fields)
        with config.db() as c:
            c.execute(f"UPDATE clips SET {cols} WHERE id = ?", (*fields.values(), clip_id))
    return _clip_or_404(clip_id)


@app.delete("/api/clips/{clip_id}")
def delete_clip(clip_id: int):
    clip = _clip_or_404(clip_id)
    if clip["render_status"] == "rendering" or "uploading" in (clip["yt_status"], clip["fb_status"]):
        raise HTTPException(409, "This clip is rendering or uploading. Wait for it to finish.")
    with config.db() as c:
        c.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
    return {"ok": True}


# ---------- rendering ----------

def _queue_render(clip: dict) -> bool:
    if clip["render_status"] in ("queued", "rendering"):
        return False
    config.update_clip(clip["id"], render_status="queued", render_progress=0, render_error=None)
    worker.enqueue_output(clip["id"], "render")
    return True


@app.post("/api/clips/{clip_id}/render")
def render_clip(clip_id: int):
    _queue_render(_clip_or_404(clip_id))
    return _clip_or_404(clip_id)


@app.post("/api/jobs/{job_id}/render-all")
def render_all(job_id: int):
    s = config.get_settings()
    n = sum(_queue_render(c) for c in list_clips(job_id) if not c["render_current"])
    return {"queued": n}


@app.post("/api/clips/{clip_id}/cancel")
def cancel_clip(clip_id: int):
    """Cancel a render or upload that hasn't started yet."""
    clip = _clip_or_404(clip_id)
    if clip["yt_status"] == "queued":
        config.update_clip(clip_id, yt_status="", yt_publish_at=None)
    if clip["fb_status"] == "queued":
        config.update_clip(clip_id, fb_status="", fb_publish_at=None)
    if clip["render_status"] == "queued":
        config.update_clip(clip_id, render_status="done" if clip["render_file"] else "")
    return _clip_or_404(clip_id)


def _safe_filename(text: str) -> str:
    keep = "".join(ch if ch.isalnum() or ch in " -_" else " " for ch in text)
    return " ".join(keep.split())[:60] or "short"


@app.get("/api/clips/{clip_id}/file")
def clip_file(clip_id: int, download: int = 0):
    clip = _clip_or_404(clip_id)
    if not clip["render_file"]:
        raise HTTPException(404, "Not rendered yet")
    path = config.job_dir(clip["job_id"]) / "clips" / clip["render_file"]
    if not path.exists():
        raise HTTPException(404, "The rendered file is missing. Render again.")
    if download:
        return FileResponse(path, media_type="video/mp4", filename=f"{_safe_filename(clip['title'])}.mp4")
    return FileResponse(path, media_type="video/mp4")


# ---------- YouTube ----------

def _redirect_uri(request: Request) -> str:
    return f"http://{HOST}:{request.url.port or PORT}/auth/youtube/callback"


@app.get("/api/youtube/status")
def youtube_status():
    return youtube.status()


@app.post("/api/youtube/client")
def youtube_client(file: UploadFile = File(...)):
    try:
        youtube.save_client(file.file.read(1_000_000))
    except youtube.YouTubeError as e:
        raise HTTPException(400, str(e))
    return youtube.status()


@app.delete("/api/youtube/client")
def youtube_remove_client():
    youtube.remove_client()
    return youtube.status()


@app.post("/api/youtube/disconnect")
def youtube_disconnect():
    youtube.disconnect()
    return youtube.status()


@app.get("/auth/youtube/start")
def youtube_auth_start(request: Request):
    if request.url.hostname != HOST:
        # Google sends you back to 127.0.0.1; start there so the browser keeps one address.
        return RedirectResponse(f"http://{HOST}:{request.url.port or PORT}/auth/youtube/start")
    try:
        return RedirectResponse(youtube.auth_url(_redirect_uri(request)))
    except youtube.YouTubeError as e:
        return RedirectResponse(f"/settings.html?yt_error={_q(str(e))}")


def _q(text: str) -> str:
    from urllib.parse import quote
    return quote(text, safe="")


@app.get("/auth/youtube/callback")
def youtube_auth_callback(request: Request, state: str = "", error: str = ""):
    if error:
        return RedirectResponse(f"/settings.html?yt_error={_q('Google sign-in was cancelled: ' + error)}")
    try:
        youtube.finish_auth(state, str(request.url))
    except youtube.YouTubeError as e:
        return RedirectResponse(f"/settings.html?yt_error={_q(str(e))}")
    return RedirectResponse("/settings.html?yt=connected")


def _taken_slots(exclude_clip: int | None = None) -> list[datetime]:
    """Publish times already used on any platform."""
    with config.db() as c:
        rows = c.execute(
            "SELECT id, yt_publish_at AS t FROM clips WHERE yt_publish_at IS NOT NULL "
            "AND yt_status IN ('queued','uploading','scheduled') "
            "UNION ALL SELECT id, fb_publish_at AS t FROM clips WHERE fb_publish_at IS NOT NULL "
            "AND fb_status IN ('queued','uploading','scheduled')").fetchall()
    return [datetime.fromisoformat(r["t"].replace("Z", "+00:00")) for r in rows if r["id"] != exclude_clip]


def _parse_when(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "Invalid publish time.")
    return when if when.tzinfo else when.astimezone()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@app.get("/api/youtube/next-slots")
def next_slots(n: int = 1, clip: int | None = None):
    slots = youtube.next_slots(max(1, min(50, n)), _taken_slots(clip), config.get_settings())
    return [_iso(t) for t in slots]


class UploadIn(BaseModel):
    publish_at: str | None = None   # ISO time; empty = publish right away
    privacy: str | None = None      # for immediate uploads: public | unlisted | private


def _queue_upload(clip: dict, publish_at: str | None, privacy: str | None) -> None:
    config.update_clip(clip["id"], yt_status="queued", yt_progress=0, yt_error=None,
                       yt_publish_at=publish_at, yt_privacy=privacy, yt_video_id=None)
    worker.enqueue_output(clip["id"], "upload")


@app.post("/api/clips/{clip_id}/youtube")
def upload_clip(clip_id: int, body: UploadIn):
    clip = _clip_or_404(clip_id)
    if not config.YT_TOKEN_PATH.exists():
        raise HTTPException(400, "Connect YouTube in Settings first.")
    if clip["yt_status"] in ("queued", "uploading"):
        raise HTTPException(409, "This clip is already being uploaded.")
    if clip["yt_status"] in ("scheduled", "published") and clip["yt_video_id"]:
        raise HTTPException(409, "This clip is already on YouTube. Change or delete it in YouTube Studio.")
    publish_at = None
    if body.publish_at:
        try:
            when = datetime.fromisoformat(body.publish_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, "Invalid publish time.")
        if when.tzinfo is None:
            when = when.astimezone()
        if when < datetime.now(timezone.utc) + timedelta(minutes=10):
            raise HTTPException(400, "Pick a publish time at least 10 minutes from now.")
        publish_at = _iso(when)
    privacy = body.privacy if body.privacy in ("public", "unlisted", "private") else None
    _queue_upload(clip, publish_at, privacy)
    return _clip_or_404(clip_id)


@app.post("/api/jobs/{job_id}/schedule-all")
def schedule_all(job_id: int, dry_run: int = 0):
    """Schedule every clip of this video that isn't posted yet, best score first, one slot per clip,
    to each platform turned on under Settings → Publishing. dry_run=1 only reports the plan."""
    s = config.get_settings()
    use_yt = bool(s["schedule_youtube"]) and config.YT_TOKEN_PATH.exists()
    use_fb = bool(s["schedule_facebook"]) and facebook.connected()
    if not (use_yt or use_fb):
        raise HTTPException(400, "Connect YouTube or Facebook in Settings (and turn it on under Publishing).")
    clips = list_clips(job_id)
    fb_len_ok = lambda c: facebook.MIN_SECONDS <= c["end"] - c["start"] <= facebook.MAX_SECONDS + 0.5
    need_yt = lambda c: use_yt and c["yt_status"] in ("", "error")
    need_fb = lambda c: use_fb and c["fb_status"] in ("", "error") and fb_len_ok(c)
    todo = sorted((c for c in clips if need_yt(c) or need_fb(c)),
                  key=lambda c: -(c["score"] if c["score"] is not None else -1))
    slots = youtube.next_slots(len(todo), _taken_slots(), s) if todo else []
    fb_limit = datetime.now(timezone.utc) + timedelta(days=29)
    too_long = sum(1 for c in clips if use_fb and c["fb_status"] in ("", "error") and not fb_len_ok(c))
    plan = {"queued": len(todo), "slots": [_iso(t) for t in slots],
            "platforms": [p for p, on in (("YouTube", use_yt), ("Facebook", use_fb)) if on],
            "fb_skipped_length": too_long,
            "fb_skipped_far": sum(1 for c, w in zip(todo, slots) if need_fb(c) and w > fb_limit)}
    if dry_run:
        return plan
    for clip, when in zip(todo, slots):
        if need_yt(clip):
            _queue_upload(clip, _iso(when), None)
        if need_fb(clip) and when <= fb_limit:
            _queue_fb(clip, _iso(when))
    return plan


# ---------- Facebook ----------

class FacebookConnect(BaseModel):
    app_id: str
    app_secret: str
    user_token: str


class FacebookPage(BaseModel):
    page_id: str


@app.get("/api/facebook/status")
def facebook_status():
    return facebook.status()


@app.post("/api/facebook/connect")
def facebook_connect(body: FacebookConnect):
    try:
        return facebook.connect(body.app_id, body.app_secret, body.user_token)
    except facebook.FacebookError as e:
        raise HTTPException(400, str(e))


@app.post("/api/facebook/page")
def facebook_page(body: FacebookPage):
    try:
        return facebook.select_page(body.page_id)
    except facebook.FacebookError as e:
        raise HTTPException(400, str(e))


@app.post("/api/facebook/disconnect")
def facebook_disconnect():
    facebook.disconnect()
    return facebook.status()


class FacebookPostIn(BaseModel):
    publish_at: str | None = None  # ISO time; empty = post right away


def _queue_fb(clip: dict, publish_at: str | None) -> None:
    config.update_clip(clip["id"], fb_status="queued", fb_progress=0, fb_error=None,
                       fb_publish_at=publish_at, fb_video_id=None)
    worker.enqueue_output(clip["id"], "fb_upload")


@app.post("/api/clips/{clip_id}/facebook")
def facebook_post(clip_id: int, body: FacebookPostIn):
    clip = _clip_or_404(clip_id)
    if not facebook.connected():
        raise HTTPException(400, "Connect a Facebook Page in Settings first.")
    if clip["fb_status"] in ("queued", "uploading"):
        raise HTTPException(409, "This clip is already being posted to Facebook.")
    if clip["fb_status"] in ("scheduled", "published") and clip["fb_video_id"]:
        raise HTTPException(409, "This clip is already on Facebook. Change or delete it in Meta Business Suite.")
    when = _parse_when(body.publish_at)
    try:
        facebook.check_length(clip["end"] - clip["start"])
        if when:
            facebook.check_schedule(when)
    except facebook.FacebookError as e:
        raise HTTPException(400, str(e))
    _queue_fb(clip, _iso(when) if when else None)
    return _clip_or_404(clip_id)


@app.get("/api/schedule")
def schedule():
    """Everything sent (or being sent) to YouTube or Facebook, across all videos."""
    with config.db() as c:
        rows = c.execute(
            "SELECT c.*, j.title AS job_title FROM clips c JOIN jobs j ON j.id = c.job_id "
            "WHERE c.yt_status != '' OR c.fb_status != '' "
            "ORDER BY COALESCE(c.yt_publish_at, c.fb_publish_at, c.yt_uploaded_at, c.created_at) DESC"
        ).fetchall()
    return [config.clip_row(r) for r in rows]


# Pages and assets. Mounted last so /api routes win.
app.mount("/fonts", StaticFiles(directory=config.FONTS_DIR), name="fonts")  # caption preview in Settings
app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    url = f"http://{HOST}:{PORT}"
    print(f"\n  Shorts Studio is running at {url}\n  Close this window (or press Ctrl+C) to stop it.\n")
    if not os.environ.get("NO_BROWSER"):
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")

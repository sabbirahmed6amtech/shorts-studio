"""Paths, settings and the SQLite database."""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
JOBS_DIR = DATA_DIR / "jobs"
MODELS_DIR = DATA_DIR / "models"
DB_PATH = DATA_DIR / "app.db"
STATIC_DIR = ROOT / "static"
FONTS_DIR = ROOT / "fonts"
YT_CLIENT_PATH = DATA_DIR / "youtube_client.json"
YT_TOKEN_PATH = DATA_DIR / "youtube_token.json"

DEFAULT_SETTINGS = {
    "gemini_api_key": "",
    "gemini_model": "gemini-3.8-flash",
    "whisper_model": "small",
    "whisper_device": "cpu",
    "language": "",            # "" = auto-detect
    "clip_min": 20,            # seconds
    "clip_max": 60,
    "clip_count": 10,
    "min_score": 0,
    "tone": "",                # extra guidance for Gemini, e.g. "educational"
    "default_hashtags": "#shorts",
    "ffmpeg_path": "",         # "" = auto-detect
    # captions
    "captions_enabled": True,
    "caption_font": "Anton",
    "caption_size": 110,       # px on a 1080x1920 frame
    "caption_color": "#FFFFFF",
    "caption_highlight": "#FFD60A",
    "caption_words": 3,        # words on screen at once
    "caption_position": 30,    # % of the height, measured up from the bottom
    "caption_uppercase": True,
    # YouTube
    "yt_category": "22",       # People & Blogs
    "yt_publish_time": "18:00",
    "yt_gap_hours": 24,
    "yt_now_privacy": "public",
    "yt_made_for_kids": False,
}

CAPTION_KEYS = [k for k in DEFAULT_SETTINGS if k.startswith("caption")]

_lock = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def job_dir(job_id: int) -> Path:
    return JOBS_DIR / str(job_id)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db():
    """One connection per use; writes are serialised by a lock (SQLite + threads)."""
    with _lock:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def init_db() -> None:
    for d in (DATA_DIR, JOBS_DIR, MODELS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,          -- 'url' | 'upload'
                url TEXT,
                title TEXT,
                status TEXT NOT NULL,          -- queued|downloading|transcribing|analyzing|ready|error
                progress REAL DEFAULT 0,       -- 0..1 within the current stage
                message TEXT,                  -- error or warning shown to the user
                ai_error TEXT,                 -- Gemini failure; job is still usable
                video_file TEXT,               -- file name inside the job folder
                video_codec TEXT,
                duration REAL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS clips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                start REAL NOT NULL,
                end REAL NOT NULL,
                score INTEGER,
                title TEXT DEFAULT '',
                description TEXT DEFAULT '',
                hashtags TEXT DEFAULT '[]',    -- JSON list
                hook TEXT DEFAULT '',
                reason TEXT DEFAULT '',
                crop_x REAL DEFAULT 0.5,       -- centre of the 9:16 crop, 0..1 of the frame width
                origin TEXT DEFAULT 'manual',  -- 'ai' | 'manual'
                edited INTEGER DEFAULT 0,      -- AI clips the user touched survive "Run AI again"
                created_at TEXT NOT NULL
            );
            """
        )
        # Columns added after the first version: add them to existing databases.
        have = {r["name"] for r in c.execute("PRAGMA table_info(clips)")}
        for col, decl in CLIP_COLUMNS:
            if col not in have:
                c.execute(f"ALTER TABLE clips ADD COLUMN {col} {decl}")


CLIP_COLUMNS = [
    ("render_status", "TEXT DEFAULT ''"),    # '' | queued | rendering | done | error
    ("render_progress", "REAL DEFAULT 0"),
    ("render_file", "TEXT"),
    ("render_sig", "TEXT"),                  # what the render was made from; differs => out of date
    ("render_error", "TEXT"),
    ("rendered_at", "TEXT"),
    ("yt_status", "TEXT DEFAULT ''"),        # '' | queued | uploading | scheduled | published | error
    ("yt_progress", "REAL DEFAULT 0"),
    ("yt_publish_at", "TEXT"),               # ISO UTC; empty = publish immediately
    ("yt_privacy", "TEXT"),
    ("yt_video_id", "TEXT"),
    ("yt_error", "TEXT"),
    ("yt_uploaded_at", "TEXT"),
]


# ---------- settings ----------

def get_settings() -> dict:
    with db() as c:
        rows = c.execute("SELECT key, value FROM settings").fetchall()
    out = dict(DEFAULT_SETTINGS)
    for r in rows:
        if r["key"] in out:
            out[r["key"]] = json.loads(r["value"])
    return out


def save_settings(values: dict) -> dict:
    current = get_settings()
    with db() as c:
        for key, value in values.items():
            if key not in DEFAULT_SETTINGS:
                continue
            default = DEFAULT_SETTINGS[key]
            if isinstance(default, bool):
                value = value in (True, 1, "1", "true", "on", "yes")
            elif isinstance(default, int):
                value = int(float(value))
            elif isinstance(default, str):
                value = str(value).strip()
            current[key] = value
            c.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )
    return current


# ---------- jobs ----------

def update_job(job_id: int, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with db() as c:
        c.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))


def get_job(job_id: int) -> dict | None:
    with db() as c:
        row = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def update_clip(clip_id: int, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with db() as c:
        c.execute(f"UPDATE clips SET {cols} WHERE id = ?", (*fields.values(), clip_id))


def get_clip(clip_id: int) -> dict | None:
    with db() as c:
        row = c.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    return clip_row(row) if row else None


def clip_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["hashtags"] = json.loads(d.get("hashtags") or "[]")
    return d

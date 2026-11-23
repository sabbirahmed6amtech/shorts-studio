"""Finding ffmpeg / ffprobe / a JS runtime, setup checks, and small media helpers."""
import json
import os
import shutil
import subprocess
import sys
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import config

IS_WINDOWS = os.name == "nt"
EXE = ".exe" if IS_WINDOWS else ""
# Keep ffmpeg from flashing a console window on Windows.
_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WINDOWS else {}


def run(args: list, **kw) -> subprocess.CompletedProcess:
    """Run a command with its arguments passed separately (never through a shell)."""
    return subprocess.run(
        [str(a) for a in args], capture_output=True, text=True,
        encoding="utf-8", errors="replace", **_NO_WINDOW, **kw,
    )


def _candidate_dirs() -> list[Path]:
    dirs = []
    custom = config.get_settings().get("ffmpeg_path", "")
    if custom:
        p = Path(custom).expanduser()
        dirs.append(p if p.is_dir() else p.parent)
    # Homebrew's plain `ffmpeg` has no subtitle support; `ffmpeg-full` is keg-only.
    dirs += [Path("/opt/homebrew/opt/ffmpeg-full/bin"), Path("/usr/local/opt/ffmpeg-full/bin")]
    if IS_WINDOWS and os.environ.get("LOCALAPPDATA"):
        dirs.append(Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "WinGet" / "Links")
    for name in ("ffmpeg",):
        found = shutil.which(name)
        if found:
            dirs.append(Path(found).parent)
    seen, out = set(), []
    for d in dirs:
        if d not in seen and (d / f"ffmpeg{EXE}").exists():
            seen.add(d)
            out.append(d)
    return out


def _has_filter(ffmpeg: Path, name: str) -> bool:
    try:
        r = run([ffmpeg, "-hide_banner", "-filters"], timeout=20)
    except Exception:
        return False
    return any(line.split()[1:2] == [name] for line in r.stdout.splitlines() if line.strip())


def _has_encoder(ffmpeg: Path, name: str) -> bool:
    try:
        r = run([ffmpeg, "-hide_banner", "-encoders"], timeout=20)
    except Exception:
        return False
    return any(line.split()[1:2] == [name] for line in r.stdout.splitlines() if line.strip())


@lru_cache(maxsize=1)
def ffmpeg_info() -> dict:
    """Pick the first ffmpeg that can burn subtitles; otherwise the first one found."""
    dirs = _candidate_dirs()
    chosen, subs = None, False
    for d in dirs:
        if _has_filter(d / f"ffmpeg{EXE}", "subtitles"):
            chosen, subs = d, True
            break
    if chosen is None and dirs:
        chosen = dirs[0]
    if chosen is None:
        return {"dir": None, "ffmpeg": None, "ffprobe": None, "subtitles": False, "libx264": False}
    ffprobe = chosen / f"ffprobe{EXE}"
    ffmpeg = chosen / f"ffmpeg{EXE}"
    return {
        "dir": str(chosen),
        "ffmpeg": str(ffmpeg),
        "ffprobe": str(ffprobe) if ffprobe.exists() else None,
        "subtitles": subs,
        "libx264": _has_encoder(ffmpeg, "libx264"),
    }


def reset_cache() -> None:
    ffmpeg_info.cache_clear()
    js_runtime.cache_clear()


@lru_cache(maxsize=1)
def js_runtime() -> tuple[str, str] | None:
    """yt-dlp needs a JavaScript runtime for YouTube. Deno is its default; Node also works."""
    for name in ("deno", "node", "bun"):
        path = shutil.which(name)
        if path:
            return name, path
    return None


def health() -> dict:
    """Setup checks shown on the home page. 'error' blocks processing; 'warn' doesn't."""
    info = ffmpeg_info()
    s = config.get_settings()
    mac = sys.platform == "darwin"
    install_ffmpeg = (
        "brew install ffmpeg-full" if mac else
        "winget install Gyan.FFmpeg  (then restart the app)" if IS_WINDOWS else
        "install ffmpeg with your package manager"
    )
    checks = []

    def add(key, ok, level, label, fix=""):
        checks.append({"key": key, "ok": ok, "level": "ok" if ok else level, "label": label, "fix": "" if ok else fix})

    add("ffmpeg", bool(info["ffmpeg"] and info["ffprobe"]), "error",
        "ffmpeg and ffprobe", f"Install it: {install_ffmpeg}")
    add("subtitles", info["subtitles"], "warn",
        "ffmpeg can burn captions",
        f"This ffmpeg has no subtitle support. Install a full build: {install_ffmpeg}")
    rt = js_runtime()
    add("js", rt is not None, "warn",
        f"JavaScript runtime for YouTube downloads{f' ({rt[0]})' if rt else ''}",
        "Install Deno (deno.com) or Node.js, or YouTube links may fail. Uploads still work.")
    add("gemini", bool(s["gemini_api_key"]), "warn",
        "Gemini API key",
        "Add your key in Settings. Without it you can still pick clips by hand.")
    add("youtube", config.YT_TOKEN_PATH.exists(), "warn",
        "YouTube channel connected",
        "Connect it in Settings to upload and schedule. You can still render and download clips.")
    return {"checks": checks, "ready": all(c["level"] != "error" for c in checks), "ffmpeg": info}


# ---------- media helpers ----------

def probe(path: Path) -> dict:
    info = ffmpeg_info()
    r = run([info["ffprobe"], "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", path], timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe could not read the video: {r.stderr.strip()[-300:]}")
    data = json.loads(r.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not video:
        raise RuntimeError("The file has no video track.")
    if not audio:
        raise RuntimeError("The file has no audio track, so there is nothing to transcribe.")
    width, height = video.get("width"), video.get("height")
    # Phone videos often store portrait footage as landscape pixels plus a rotation flag.
    # ffmpeg applies the rotation when decoding, so swap to the size you actually see.
    rotation = 0
    for sd in video.get("side_data_list") or []:
        if "rotation" in sd:
            rotation = int(float(sd["rotation"]))
    rotation = rotation or int(float((video.get("tags") or {}).get("rotate", 0) or 0))
    if abs(rotation) % 180 == 90:
        width, height = height, width
    fps = None
    try:
        num, den = (video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1").split("/")
        fps = float(num) / float(den) if float(den) else None
    except (ValueError, ZeroDivisionError):
        pass
    return {
        "fps": fps,
        "duration": float(data.get("format", {}).get("duration") or 0),
        "vcodec": video.get("codec_name"),
        "acodec": audio.get("codec_name"),
        "width": width,
        "height": height,
    }


def extract_audio(video: Path, out_wav: Path) -> None:
    """16 kHz mono WAV: what Whisper wants, and cheap to compute waveform peaks from."""
    tmp = out_wav.with_suffix(".tmp.wav")
    r = run([ffmpeg_info()["ffmpeg"], "-y", "-hide_banner", "-loglevel", "error",
             "-i", video, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", tmp])
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg could not extract audio: {r.stderr.strip()[-300:]}")
    tmp.replace(out_wav)


def compute_peaks(wav_path: Path, out_json: Path, per_second: int = 20) -> None:
    """Pre-compute the waveform so the browser never decodes an hour of audio."""
    with wave.open(str(wav_path), "rb") as w:
        rate = w.getframerate()
        frames = w.readframes(w.getnframes())
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    bucket = max(1, rate // per_second)
    n = len(samples) // bucket
    if n == 0:
        peaks = []
    else:
        peaks = np.abs(samples[: n * bucket].reshape(n, bucket)).max(axis=1)
        top = float(peaks.max()) or 1.0
        peaks = np.round(peaks / top, 3).tolist()
    out_json.write_text(json.dumps({"per_second": per_second, "peaks": peaks}), encoding="utf-8")

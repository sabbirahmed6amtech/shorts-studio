"""Download a video with yt-dlp into the job folder."""
from pathlib import Path
from typing import Callable

import yt_dlp

from . import tools

# Prefer H.264 + AAC in MP4 so every browser can play it in the editor.
FORMAT = (
    "bv*[vcodec^=avc1][height<=1080]+ba[acodec^=mp4a]/"
    "b[vcodec^=avc1][height<=1080][ext=mp4]/"
    "bv*[height<=1080]+ba/b"
)


def download(url: str, dest_dir: Path, on_progress: Callable[[float], None]) -> tuple[Path, str]:
    """Returns (video path, title)."""

    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                on_progress(min(1.0, d.get("downloaded_bytes", 0) / total))

    opts = {
        "format": FORMAT,
        "merge_output_format": "mp4",
        # Name by a fixed word, never the video title: titles can hold characters Windows forbids.
        "outtmpl": str(dest_dir / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [hook],
    }
    ff = tools.ffmpeg_info()
    if ff["dir"]:
        opts["ffmpeg_location"] = ff["dir"]
    rt = tools.js_runtime()
    if rt:
        opts["js_runtimes"] = {rt[0]: {"path": rt[1]}}

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info.get("_type") == "playlist":
            raise RuntimeError("That link is a playlist. Paste a single video link.")
        title = info.get("title") or "Untitled"

    files = [p for p in dest_dir.glob("source.*") if p.suffix not in (".part", ".ytdl") and ".f" not in p.stem]
    if not files:
        raise RuntimeError("yt-dlp finished but no video file was saved.")
    return max(files, key=lambda p: p.stat().st_size), title

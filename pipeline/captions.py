"""YouTube's own captions as a fast alternative to Whisper.

Fetched with yt-dlp in YouTube's json3 format. Auto-generated captions carry a time for
every word, so word-by-word captions stay in sync. Captions typed by the creator only
have line times, so words are spread across each line by length.
"""
import json
import re
from pathlib import Path

import yt_dlp

from . import tools
from .transcribe import build_lines

_TAG = re.compile(r"^\[.*\]$")  # [Music], [Applause]


def _pick_language(info: dict, wanted: str) -> tuple[str, bool] | None:
    """(caption key, is_auto). Prefers the video's own language over YouTube's machine translations."""
    manual = {k: v for k, v in (info.get("subtitles") or {}).items() if k != "live_chat"}
    auto = info.get("automatic_captions") or {}
    lang = wanted or info.get("language") or ""
    if lang:
        for key in (lang, *[k for k in manual if k.split("-")[0] == lang]):
            if key in manual:
                return key, False
        for key in (f"{lang}-orig", lang):
            if key in auto:
                return key, True
    if wanted:
        return None  # asked for a language the video doesn't have
    orig = next((k for k in auto if k.endswith("-orig")), None)  # the speech recognised in its own language
    if orig:
        return orig, True
    if manual:
        return next(iter(manual)), False
    return None


def fetch(url: str, dest_dir: Path, language: str = "") -> tuple[Path | None, str]:
    """Download the best caption track. Returns (file or None, a note for the user)."""
    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True, "skip_download": True}
    rt = tools.js_runtime()
    if rt:
        opts["js_runtimes"] = {rt[0]: {"path": rt[1]}}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info.get("extractor_key") != "Youtube":
                return None, "Not a YouTube video, so there are no YouTube captions."
            pick = _pick_language(info, language)
            if not pick:
                return None, "This video has no YouTube captions" + (f" in '{language}'." if language else ".")
            key, is_auto = pick
            ydl.params.update({
                "writesubtitles": not is_auto, "writeautomaticsub": is_auto,
                "subtitleslangs": [key], "subtitlesformat": "json3",
                "outtmpl": {"default": str(dest_dir / "captions.%(ext)s")},
            })
            ydl.process_ie_result(info, download=True)
    except Exception as e:
        return None, f"Couldn't get YouTube captions ({str(e)[:120]})."
    files = sorted(dest_dir.glob("captions*.json3"))
    if not files:
        return None, "YouTube didn't return the captions."
    return files[0], ""


def parse(path: Path, duration: float) -> dict:
    """json3 -> the same transcript shape Whisper produces."""
    data = json.loads(path.read_text(encoding="utf-8"))
    words = []
    for ev in data.get("events") or []:
        segs = ev.get("segs") or []
        t0 = ev.get("tStartMs", 0) / 1000
        t1 = t0 + ev.get("dDurationMs", 0) / 1000
        if not segs:
            continue
        if len(segs) > 1 and any("tOffsetMs" in s for s in segs):
            # Auto captions: each seg is a word with its own start time.
            for s in segs:
                text = s.get("utf8", "").strip()
                if text and not _TAG.match(text):
                    words.append({"s": t0 + s.get("tOffsetMs", 0) / 1000, "e": t1, "w": text})
        else:
            # Typed captions: one line; spread the words across it by length.
            tokens = [t for t in "".join(s.get("utf8", "") for s in segs).split() if not _TAG.match(t)]
            total = sum(len(t) + 1 for t in tokens) or 1
            pos = t0
            for t in tokens:
                span = (t1 - t0) * (len(t) + 1) / total
                words.append({"s": pos, "e": pos + span, "w": t})
                pos += span
    words.sort(key=lambda w: w["s"])
    for i, w in enumerate(words):  # a word ends when the next starts (capped), never after the video
        nxt = words[i + 1]["s"] if i + 1 < len(words) else w["e"]
        w["e"] = round(min(w["e"], nxt, w["s"] + 1.2, duration or 1e9), 2)
        w["s"] = round(w["s"], 2)
        if w["e"] <= w["s"]:
            w["e"] = round(w["s"] + 0.1, 2)
    lang = path.stem.split(".")[-1].replace("-orig", "") if "." in path.stem else ""
    return {"language": lang, "duration": duration, "words": words, "lines": build_lines(words), "source": "youtube"}

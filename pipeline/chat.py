"""Live chat replay as a signal: where chat explodes in a past live stream.

yt-dlp downloads the replay (a JSON line per chat action, with the time into the video).
It's kept as messages per second plus a few short sample messages, and the raw file
(tens of MB for a long stream) is deleted.
"""
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
import yt_dlp

from . import tools

MESSAGE_KINDS = ("liveChatTextMessageRenderer", "liveChatPaidMessageRenderer", "liveChatPaidStickerRenderer")
_SPACE = re.compile(r"\s+")


def fetch(url: str, dest_dir: Path) -> tuple[Path | None, str]:
    """Download the chat replay if the video was a live stream with chat. (file or None, note)."""
    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True, "skip_download": True}
    rt = tools.js_runtime()
    if rt:
        opts["js_runtimes"] = {rt[0]: {"path": rt[1]}}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info.get("extractor_key") != "Youtube" or "live_chat" not in (info.get("subtitles") or {}):
                return None, ""  # not a past stream, or chat replay is off: nothing to say
            ydl.params.update({"writesubtitles": True, "subtitleslangs": ["live_chat"],
                               "outtmpl": {"default": str(dest_dir / "chat_raw.%(ext)s")}})
            ydl.process_ie_result(info, download=True)
    except Exception as e:
        return None, f"Couldn't read the live chat ({str(e)[:100]})."
    raw = next(iter(dest_dir.glob("chat_raw*.json")), None)
    return (raw, "") if raw else (None, "YouTube didn't return the live chat.")


def _text(renderer: dict) -> str:
    runs = (renderer.get("message") or {}).get("runs") or []
    parts = []
    for r in runs:
        if "text" in r:
            parts.append(r["text"])
        elif "emoji" in r:  # keep emoji as their short name, e.g. :face-with-tears-of-joy:
            sc = (r["emoji"].get("shortcuts") or [""])[0]
            parts.append(sc)
    return _SPACE.sub(" ", "".join(parts)).strip()


def parse(raw: Path, out: Path, duration: float) -> dict:
    """Raw replay -> {"per_second": [...], "samples": {"second": ["msg", ...]}}; deletes the raw file."""
    n = max(1, int(duration) + 1)
    counts = [0] * n
    samples: dict[int, list[str]] = {}
    with open(raw, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            r = d.get("replayChatItemAction") or {}
            try:
                sec = int(r.get("videoOffsetTimeMsec", -1)) // 1000
            except (TypeError, ValueError):
                continue
            if sec <= 0 or sec >= n:  # messages from the waiting room before the stream starts
                continue
            for a in r.get("actions") or []:
                item = (a.get("addChatItemAction") or {}).get("item") or {}
                kind = next((k for k in MESSAGE_KINDS if k in item), None)
                if not kind:
                    continue
                counts[sec] += 1
                text = _text(item[kind])
                if text and len(text) <= 40 and len(samples.setdefault(sec, [])) < 4:
                    samples[sec].append(text)
    data = {"per_second": counts, "samples": {str(k): v for k, v in samples.items()}, "total": sum(counts)}
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    try:
        raw.unlink()
    except OSError:
        pass
    return data


def spikes(chat: dict, lag: tuple[int, int] = (3, 15)):
    """Returns a function (start, end) -> (ratio, sample messages) for a stretch of video.

    Chat reacts a few seconds after a moment (stream delay plus typing), so each stretch is
    measured over [start + 3s, end + 15s], compared with the usual rate around that point
    (the median of the surrounding 10 minutes, since chat grows and shrinks over a stream)."""
    counts = np.array(chat.get("per_second") or [], dtype=float)
    if counts.size == 0 or counts.sum() < 30:
        return None
    win = 600
    # Rolling median of 10-second rates over ±5 minutes, sampled every 30s to keep it cheap.
    rate10 = np.convolve(counts, np.ones(10), mode="same") / 10
    marks = np.arange(0, counts.size, 30)
    med = np.array([np.median(rate10[max(0, m - win // 2): m + win // 2]) for m in marks])
    floor = max(0.05, float(np.median(rate10[rate10 > 0])) * 0.3) if (rate10 > 0).any() else 0.05
    samples = chat.get("samples") or {}

    def measure(start: float, end: float):
        a = int(start) + lag[0]
        b = max(a + 1, int(end) + lag[1])
        seg = counts[a:b]
        if seg.size == 0:
            return 1.0, []
        rate = float(seg.sum()) / seg.size
        base = max(floor, float(med[min(len(med) - 1, int((start + end) / 2) // 30)]))
        msgs = Counter()
        for sec in range(a, b):
            for m in samples.get(str(sec), []):
                msgs[m.lower()] += 1
        top = [m for m, _ in msgs.most_common(3)]
        return rate / base, top

    return measure

"""Render a clip: cut, crop to 9:16, scale to 1080x1920, burn in word-by-word captions."""
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from . import config, tools

OUT_W, OUT_H = 1080, 1920
SENTENCE_END = (".", "?", "!", "…", "。", "？", "！")


def job_layout(job: dict) -> dict | None:
    """The split layout of a video, or None for the normal single crop."""
    if (job or {}).get("layout") != "split" or not job.get("layout_json"):
        return None
    data = json.loads(job["layout_json"])
    data["split"] = min(0.6, max(0.25, float(data.get("split", 0.4))))
    return data


def render_sig(clip: dict, settings: dict, job: dict | None = None) -> str:
    """Fingerprint of everything that changes the output; a different value means re-render."""
    if job is None:
        job = config.get_job(clip["job_id"])
    layout = job_layout(job)
    data = {"start": clip["start"], "end": clip["end"],
            "crop": layout if layout else round(clip.get("crop_x") or 0.5, 3),
            "hook": clip.get("hook_title") or "",
            **{k: settings[k] for k in config.CAPTION_KEYS}}
    return hashlib.sha1(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


# ---------- captions (ASS subtitles) ----------

def _ass_color(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


# The caption renderer can't draw colour emoji; drop them (but keep U+200C/U+200D,
# which Bengali and other scripts need to join letters).
_EMOJI = re.compile("[\U0001F000-\U0001FFFF\u2600-\u27BF\u2B00-\u2BFF\uFE0E\uFE0F\u20E3]")
_BENGALI = re.compile("[\u0980-\u09FF]")
BENGALI_FONT = "Noto Sans Bengali"  # bundled in fonts/, so Windows and Mac render the same


def _clean(word: str, upper: bool, base_font: str = "") -> str:
    # Braces and backslashes are ASS control characters.
    word = _EMOJI.sub("", word).replace("\\", "/").replace("{", "(").replace("}", ")")
    if upper:
        word = word.upper()
    if base_font and _BENGALI.search(word):
        # Display fonts like Anton have no Bengali letters: switch font for this word only.
        word = f"{{\\fn{BENGALI_FONT}\\b1}}{word}{{\\fn{base_font}\\b0}}"
    return word


def caption_chunks(words: list[dict], start: float, end: float, per_chunk: int, max_gap: float = 0.7):
    """Words inside the clip, re-timed from 0, grouped into on-screen chunks."""
    inside = [
        {"s": max(0.0, w["s"] - start), "e": min(end, w["e"]) - start, "w": w["w"]}
        for w in words if w["e"] > start + 0.05 and w["s"] < end - 0.05
    ]
    chunks, cur = [], []
    for w in inside:
        if cur and (len(cur) >= per_chunk or w["s"] - cur[-1]["e"] > max_gap):
            chunks.append(cur)
            cur = []
        cur.append(w)
        if w["w"].endswith(SENTENCE_END):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def build_ass(words: list[dict], clip: dict, s: dict, split: float | None = None, captions: bool = True) -> str:
    primary, highlight = _ass_color(s["caption_color"]), _ass_color(s["caption_highlight"])
    size = max(30, min(200, int(s["caption_size"])))
    font = s["caption_font"]
    if split:  # streamer + content: centre the captions on the line between the two parts
        margin_v = int(OUT_H * (1 - split) - size * 0.55)
    else:
        margin_v = int(OUT_H * max(2, min(90, int(s["caption_position"]))) / 100)

    # Hook title: a boxed banner for the first seconds. At the top for a single crop; on the
    # line between the parts for streamer + content, so it doesn't cover the streamer's face.
    hook = _EMOJI.sub("", clip.get("hook_title") or "").replace("\n", " ").strip()
    hook_on = bool(s["hook_enabled"]) and bool(hook)
    hook_secs = max(1, min(10, int(s["hook_seconds"])))
    hook_size = max(30, min(160, int(s["hook_size"])))
    pad = max(10, hook_size // 3)
    if split:
        hook_margin = int(OUT_H * (1 - split) - hook_size * 0.6)  # centred on the seam
        cap_low = max(40, margin_v - int(hook_size * 2.6))        # captions move down while it shows
    else:
        hook_margin = int(OUT_H * 0.10)
        cap_low = margin_v
    hook_align = 2 if split else 8  # 2 = bottom-centre anchor (seam), 8 = top-centre
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {OUT_W}
PlayResY: {OUT_H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},{primary},{primary},&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,{max(2, size // 14)},2,2,80,80,{margin_v},1
Style: CapLow,{font},{size},{primary},{primary},&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,{max(2, size // 14)},2,2,80,80,{cap_low},1
Style: Hook,{font},{hook_size},{_ass_color(s['hook_color'])},{_ass_color(s['hook_color'])},{_ass_color(s['hook_bg'])},{_ass_color(s['hook_bg'])},0,0,0,0,100,100,0,0,3,{pad},0,{hook_align},110,110,{hook_margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    duration = clip["end"] - clip["start"]
    upper = bool(s["caption_uppercase"])
    lines = []
    if hook_on:
        text = " ".join(_clean(w, upper, font) for w in hook.split())
        lines.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(min(hook_secs, duration))},Hook,,0,0,0,,{{\\fad(150,250)}}{text}")
    chunks = caption_chunks(words, clip["start"], clip["end"], max(1, int(s["caption_words"]))) if captions else []
    for ci, chunk in enumerate(chunks):
        next_start = chunks[ci + 1][0]["s"] if ci + 1 < len(chunks) else duration
        for i, w in enumerate(chunk):
            t0 = chunk[0]["s"] if i == 0 else w["s"]
            t1 = chunk[i + 1]["s"] if i + 1 < len(chunk) else min(next_start, w["e"] + 0.4)
            if t1 - t0 < 0.02:
                continue
            text = " ".join(
                f"{{\\c{highlight}}}{_clean(x['w'], upper, font)}{{\\c{primary}}}" if j == i else _clean(x["w"], upper, font)
                for j, x in enumerate(chunk)
            )
            style = "CapLow" if hook_on and split and t0 < hook_secs else "Cap"
            lines.append(f"Dialogue: 0,{_ass_time(t0)},{_ass_time(t1)},{style},,0,0,0,,{text}")
    return header + "\n".join(lines) + "\n"


# ---------- crop ----------

def crop_box(width: int, height: int, crop_x: float) -> tuple[int, int, int, int]:
    """(w, h, x, y) of the 9:16 window inside the source frame."""
    if width / height > 9 / 16:  # wider than 9:16 (the usual case): crop the sides
        cw, ch = int(height * 9 / 16) // 2 * 2, height // 2 * 2
        x = int(round(crop_x * width - cw / 2))
        return cw, ch, max(0, min(width - cw, x)), 0
    cw, ch = width // 2 * 2, int(width * 16 / 9) // 2 * 2  # already tall: trim top and bottom evenly
    return cw, ch, 0, max(0, (height - ch) // 2)


def fit_rect(r: dict, width: int, height: int, out_w: int, out_h: int) -> tuple[int, int, int, int]:
    """Pixel crop (w, h, x, y) for a 0..1 rect, shrunk around its centre to exactly the output's
    shape so nothing is stretched, and kept inside the frame."""
    w, h = max(0.02, r["w"]) * width, max(0.02, r["h"]) * height
    cx, cy = (r["x"] + r["w"] / 2) * width, (r["y"] + r["h"] / 2) * height
    target = out_w / out_h
    if w / h > target:
        w = h * target
    else:
        h = w / target
    w, h = min(w, width), min(h, height)
    w, h = max(2, int(w) // 2 * 2), max(2, int(h) // 2 * 2)
    x = int(round(min(max(cx - w / 2, 0), width - w)))
    y = int(round(min(max(cy - h / 2, 0), height - h)))
    return w, h, x, y


def _filter_path(path: Path, cwd: Path) -> str:
    """A path ffmpeg's filter syntax accepts. ':' is a separator there, which breaks Windows
    drive letters (C:\\...), so prefer a relative path; otherwise escape the colon."""
    try:
        rel = os.path.relpath(path, cwd)  # ValueError on Windows when on another drive
        if ":" not in rel:
            return Path(rel).as_posix().replace("'", "\\'")
    except ValueError:
        pass
    return path.resolve().as_posix().replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


# ---------- render ----------

def render(clip: dict, job: dict, settings: dict, on_progress: Callable[[float], None]) -> Path:
    info = tools.ffmpeg_info()
    if not info["ffmpeg"]:
        raise RuntimeError("ffmpeg is not installed.")
    if not info["libx264"]:
        raise RuntimeError("This ffmpeg has no H.264 encoder (libx264). Install a full ffmpeg build.")
    captions = bool(settings["captions_enabled"])
    hook = bool(settings["hook_enabled"]) and bool((clip.get("hook_title") or "").strip())
    if (captions or hook) and not info["subtitles"]:
        raise RuntimeError("This ffmpeg can't draw captions or hook titles. Install a full build (see the home "
                           "page), or turn captions and hook titles off in Settings.")

    jdir = config.job_dir(job["id"])
    src = jdir / job["video_file"]
    meta = tools.probe(src)
    out_dir = jdir / "clips"
    out_dir.mkdir(exist_ok=True)

    layout = job_layout(job)
    if layout:
        # Streamer on top, content below, stacked into one 1080x1920 frame.
        top_h = int(OUT_H * layout["split"]) // 2 * 2
        bot_h = OUT_H - top_h
        a = fit_rect(layout["cam"], meta["width"], meta["height"], OUT_W, top_h)
        b = fit_rect(layout["content"], meta["width"], meta["height"], OUT_W, bot_h)
        vf = (f"split=2[a][b];"
              f"[a]crop={a[0]}:{a[1]}:{a[2]}:{a[3]},scale={OUT_W}:{top_h}:flags=lanczos,setsar=1[top];"
              f"[b]crop={b[0]}:{b[1]}:{b[2]}:{b[3]},scale={OUT_W}:{bot_h}:flags=lanczos,setsar=1[bot];"
              f"[top][bot]vstack=inputs=2")
    else:
        cw, ch, x, y = crop_box(meta["width"], meta["height"], clip.get("crop_x") or 0.5)
        vf = f"crop={cw}:{ch}:{x}:{y},scale={OUT_W}:{OUT_H}:flags=lanczos,setsar=1"
    # Facebook Reels need 24-60 fps (YouTube is fine either way).
    if meta.get("fps") and meta["fps"] < 23.5:
        vf += ",fps=30"
    elif meta.get("fps") and meta["fps"] > 60.5:
        vf += ",fps=60"

    ass_path = out_dir / f"clip_{clip['id']}.ass"
    if captions or hook:
        words = json.loads((jdir / "transcript.json").read_text(encoding="utf-8"))["words"] if captions else []
        ass_path.write_text(build_ass(words, clip, settings, layout["split"] if layout else None, captions),
                            encoding="utf-8")
        # ffmpeg runs inside the clips folder, so the subtitle file needs no path at all.
        vf += f",subtitles=filename='{ass_path.name}':fontsdir='{_filter_path(config.FONTS_DIR, out_dir)}'"

    # A new file name per render: Windows can't overwrite a file the browser is still playing.
    n = 1 + max([int(p.stem.rsplit("_", 1)[-1]) for p in out_dir.glob(f"clip_{clip['id']}_*.mp4")
                 if p.stem.rsplit("_", 1)[-1].isdigit()] or [0])
    out = out_dir / f"clip_{clip['id']}_{n}.mp4"
    tmp = out.with_suffix(".part.mp4")
    duration = clip["end"] - clip["start"]

    args = [
        info["ffmpeg"], "-y", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1",
        "-ss", f"{clip['start']:.3f}", "-i", str(src), "-t", f"{duration:.3f}",
        "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        "-movflags", "+faststart", str(tmp),
    ]
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as err:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=err, text=True, cwd=out_dir,
                                encoding="utf-8", errors="replace",
                                **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
        for line in proc.stdout:
            key, _, val = line.strip().partition("=")
            if key in ("out_time_us", "out_time_ms") and val.isdigit() and duration > 0:
                on_progress(min(0.99, int(val) / 1_000_000 / duration))
        proc.wait()
        if proc.returncode != 0:
            err.seek(0)
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"ffmpeg failed: {err.read().strip()[-400:]}")
    tmp.replace(out)
    on_progress(1.0)
    return out

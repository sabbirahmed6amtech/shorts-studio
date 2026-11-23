"""Loudness hints for Gemini.

Gemini only reads text. In streams and gameplay the best moments are often loud
(shouting, laughing, explosions) and sometimes have no speech at all. This marks
each transcript line with how loud it is compared with the rest of the video, and
fills stretches without speech with short "(no speech)" lines so Gemini can still
pick them.
"""
import math
import wave
from pathlib import Path

import numpy as np


def levels(wav: Path) -> np.ndarray:
    """Loudness per second, in dB (RMS)."""
    with wave.open(str(wav), "rb") as w:
        rate = w.getframerate()
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    n = len(samples) // rate
    if n == 0:
        return np.array([])
    rms = np.sqrt(np.mean(samples[: n * rate].reshape(n, rate) ** 2, axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-4))  # floor at -80 dB


def annotate(lines: list[dict], wav: Path, duration: float, gap: float = 4.0, chunk: float = 5.0) -> list[dict]:
    """Copy of the lines with a 'loud' label, plus '(no speech)' lines for gaps of 4s or more."""
    db = levels(wav)
    if db.size == 0:
        return lines
    heard = db[db > -60] if (db > -60).any() else db  # ignore true silence when ranking
    q75, q95 = np.percentile(heard, 75), np.percentile(heard, 95)

    def label(s: float, e: float) -> str:
        seg = db[int(s): max(int(s) + 1, math.ceil(e))]
        if seg.size == 0:
            return "normal"
        peak = float(seg.max())
        if peak >= q95 and peak >= q75 + 3:
            return "very loud"
        if peak >= q75 + 1.5:
            return "loud"
        if float(seg.mean()) < -50:
            return "silent"
        return "normal"

    def fill(a: float, b: float, out: list):
        if b - a < gap:
            return
        n = max(1, round((b - a) / chunk))
        step = (b - a) / n
        for i in range(n):
            s, e = a + i * step, a + (i + 1) * step
            out.append({"start": round(s, 2), "end": round(e, 2), "text": "", "nospeech": True, "loud": label(s, e)})

    out, cursor = [], 0.0
    for line in sorted(lines, key=lambda l: l["start"]):
        fill(cursor, line["start"], out)
        out.append({**line, "loud": label(line["start"], line["end"])})
        cursor = max(cursor, line["end"])
    fill(cursor, duration or len(db), out)
    return out

"""Speech to text with word timestamps (faster-whisper), split into short numbered lines."""
import json
import threading
import wave
from pathlib import Path
from typing import Callable

from . import config

_model = None
_model_key = None
_model_lock = threading.Lock()

SENTENCE_END = (".", "?", "!", "…", "。", "？", "！")


def _get_model(size: str, device: str):
    global _model, _model_key
    from faster_whisper import WhisperModel  # slow import; only when needed

    key = (size, device)
    with _model_lock:
        if _model is None or _model_key != key:
            compute = "float16" if device in ("cuda", "mps") else "int8"
            _model = WhisperModel(size, device=device, compute_type=compute,
                                  download_root=str(config.MODELS_DIR))
            _model_key = key
    return _model


def transcribe(wav: Path, out_json: Path, settings: dict, on_progress: Callable[[float], None]) -> dict:
    import numpy as np

    model = _get_model(settings["whisper_model"], settings["whisper_device"])
    # Hand Whisper the samples directly instead of a file path: its file decoder depends on
    # PyAV, whose API changes between releases (PyAV 19 broke faster-whisper 1.2).
    with wave.open(str(wav), "rb") as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    segments, info = model.transcribe(
        audio,
        language=settings["language"] or None,
        word_timestamps=True,
        vad_filter=True,
        beam_size=1 if settings.get("whisper_fast", True) else 5,
    )
    words = []
    for seg in segments:  # generator: transcription happens while iterating
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append({"s": round(w.start, 2), "e": round(w.end, 2), "w": text})
        if info.duration:
            on_progress(min(1.0, seg.end / info.duration))

    data = {"language": info.language, "duration": info.duration, "words": words,
            "lines": build_lines(words), "source": "whisper"}
    out_json.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def build_lines(words: list[dict], max_words: int = 18, max_gap: float = 1.2) -> list[dict]:
    """Group words into sentence-sized lines. Gemini picks clips by line number,
    so every clip boundary lands exactly on a word boundary."""
    lines, cur = [], []

    def flush():
        if cur:
            lines.append({
                "start": cur[0]["s"], "end": cur[-1]["e"],
                "text": " ".join(w["w"] for w in cur),
                "w0": cur[0]["i"], "w1": cur[-1]["i"],
            })
            cur.clear()

    for i, w in enumerate(words):
        if cur and (w["s"] - cur[-1]["e"] > max_gap):
            flush()
        cur.append({**w, "i": i})
        if w["w"].endswith(SENTENCE_END) or len(cur) >= max_words:
            flush()
    flush()
    return lines

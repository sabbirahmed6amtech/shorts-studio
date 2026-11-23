"""Ask Gemini for clip suggestions + metadata, then clean up what it returns."""
import time

from pydantic import BaseModel, Field

from google import genai
from google.genai import errors, types


class ClipSuggestion(BaseModel):
    start_line: int = Field(description="Line number (Lnn) where the clip starts")
    end_line: int = Field(description="Line number (Lnn) where the clip ends, inclusive")
    score: int = Field(description="Virality score 0-100")
    hook: str = Field(description="The opening line that grabs attention")
    reason: str = Field(description="One sentence: why this works as a Short")
    title: str = Field(description="YouTube Shorts title, under 70 characters, no hashtags")
    hook_title: str = Field(description="Big text banner shown on the video for its first seconds: "
                                        "3 to 7 punchy words that make people stay, no emoji, no hashtags")
    description: str = Field(description="2-3 sentence YouTube description")
    hashtags: list[str] = Field(description="3-6 relevant hashtags, each starting with #")


class AIError(Exception):
    """A Gemini failure worded for the user."""


def _fmt(t: float) -> str:
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def _line(i: int, l: dict) -> str:
    loud = l.get("loud")
    marks = []
    if l.get("nospeech"):
        marks.append("no speech")
    m = {"loud": "LOUD", "very loud": "VERY LOUD", "silent": "silent" if l.get("nospeech") else ""}.get(loud, "")
    if m:
        marks.append(m)
    if l.get("chat"):
        msgs = ", ".join('"' + x.replace('"', "'")[:30] + '"' for x in (l.get("chat_msgs") or []))
        marks.append(f"CHAT x{l['chat']:g}" + (f": {msgs}" if msgs else ""))
    head = f"L{i} [{_fmt(l['start'])}]"
    tag = f"({' · '.join(marks)})" if marks else ""
    return " ".join(x for x in (head, tag, l.get("text", "")) if x)


def build_prompt(lines: list[dict], s: dict, title: str = "") -> str:
    transcript = "\n".join(_line(i, l) for i, l in enumerate(lines))
    tone = f"\nThe creator wants clips that are: {s['tone']}." if s.get("tone") else ""
    has_sound = any("loud" in l for l in lines)
    has_chat = any("chat" in l for l in lines)
    speech = any(not l.get("nospeech") for l in lines)
    sound_help = """
Some lines carry sound markers. (LOUD) and (VERY LOUD) mean the audio there is much
louder than usual for this video: shouting, laughing, cheering, explosions or a big
in-game moment. "(no speech)" lines are stretches without talking, with their loudness.
In streams and gaming videos the loudest moments are often the most exciting, so a
strong clip can build up to a loud moment and include its reaction. Clips may include
no-speech lines.
""" if has_sound else ""
    chat_help = """
This was a live stream. (CHAT x3: "w", "no way") means viewers sent messages 3 times
faster than usual right after this line, with a few of the messages they sent. Chat
reacts 5-15 seconds after something happens, so the moment itself is usually on this
line or just before it. Big chat spikes are strong evidence of a clip-worthy moment;
read the messages to understand what happened (but ignore spikes where the streamer
just asked chat to type something).
""" if has_chat else ""
    no_speech_help = """
There is little or no speech in this video, so judge mainly by loudness and pacing,
and write titles from the video title and what the sound suggests is happening.
""" if not speech else ""
    return f"""You are an expert short-form video editor. Below is a transcript of a long video,
split into numbered lines (L0, L1, ...) with timestamps.
{f'Video title: {title}' if title else ''}
Find up to {s['clip_count']} segments that would work as standalone YouTube Shorts.
Each segment must:
- run between {s['clip_min']} and {s['clip_max']} seconds (use the timestamps),
- open with a strong hook in the first line (a question, bold claim, surprise, emotion or sudden action),
- be a complete moment that makes sense without the rest of the video,
- end on a payoff, not mid-idea,
- not overlap other segments.{tone}
{sound_help}{chat_help}{no_speech_help}
Score each 0-100 for how likely it is to perform well as a Short (hook strength,
clarity without context, emotional or surprising payoff, broad interest).
For each segment also write a hook_title: a short on-screen banner (3-7 words, no emoji)
that teases the payoff and makes viewers keep watching, e.g. "He tried to get GTA 6 for free".
Write the title, hook_title, description and hashtags in the same language as the transcript
(or the video title if there is no speech).
Return the segments using line numbers, best first.

TRANSCRIPT:
{transcript}
"""


def suggest(lines: list[dict], s: dict, title: str = "") -> list[ClipSuggestion]:
    if not s.get("gemini_api_key"):
        raise AIError("No Gemini API key. Add one in Settings, then press Run AI again.")
    if not lines:
        raise AIError("No speech was found, so there is nothing for Gemini to read. "
                      "Turn on Loudness hints in Settings so Gemini can pick loud moments, then press Run AI again.")
    # Never wait forever: 2 minutes per attempt.
    client = genai.Client(api_key=s["gemini_api_key"], http_options=types.HttpOptions(timeout=120_000))
    prompt = build_prompt(lines, s, title)
    models = [s["gemini_model"]]
    if s.get("gemini_fallback_model") and s["gemini_fallback_model"] != s["gemini_model"]:
        models.append(s["gemini_fallback_model"])
    try:
        for attempt in range(len(models) + 2):
            # Two tries on the main model, then the backup model if Google is still overloaded.
            model = models[0] if attempt < 2 or len(models) == 1 else models[1]
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=list[ClipSuggestion],
                    ),
                )
                break
            except errors.APIError as e:
                # 500/503 ("high demand") are usually brief on Google's side: wait and try again.
                if getattr(e, "code", None) in (500, 502, 503, 504) and attempt < len(models) + 1:
                    time.sleep(8 if attempt < 1 else 3)
                    continue
                raise
    except errors.APIError as e:
        code = getattr(e, "code", None)
        if code in (500, 502, 503, 504):
            raise AIError("Gemini is overloaded right now (Google's side). Wait a few minutes, then press Run AI again.")
        if code == 429:
            raise AIError("Gemini rate limit reached (free tier). Wait a minute, then press Run AI again.")
        if code == 404:
            raise AIError(f"Gemini model '{s['gemini_model']}' was not found. Change the model in Settings.")
        if code in (400, 401, 403) and "key" in str(e).lower():
            raise AIError("Gemini rejected the API key. Check it in Settings.")
        raise AIError(f"Gemini error {code}: {getattr(e, 'message', None) or e}")
    except Exception as e:  # network, timeout etc.
        if "timeout" in type(e).__name__.lower() or "timed out" in str(e).lower():
            raise AIError("Gemini took more than 2 minutes to answer. Press Run AI again.")
        raise AIError(f"Could not reach Gemini: {e}")

    parsed = resp.parsed
    if not isinstance(parsed, list):
        raise AIError("Gemini returned an answer that was not a list of clips. Press Run AI again.")
    return parsed


def to_clips(suggestions: list[ClipSuggestion], lines: list[dict], s: dict, duration: float,
             default_tags: list[str]) -> list[dict]:
    """Treat Gemini's output as untrusted: fix line ranges, enforce length, drop overlaps."""
    n = len(lines)
    lo, hi = float(s["clip_min"]), float(s["clip_max"])
    out = []
    for sug in suggestions:
        a, b = sorted((sug.start_line, sug.end_line))
        if a >= n or b < 0:
            continue
        a, b = max(0, a), min(n - 1, b)
        # Too long: drop lines from the end. Too short: add following lines.
        while b > a and lines[b]["end"] - lines[a]["start"] > hi:
            b -= 1
        while b + 1 < n and lines[b]["end"] - lines[a]["start"] < lo and lines[b + 1]["end"] - lines[a]["start"] <= hi:
            b += 1
        length = lines[b]["end"] - lines[a]["start"]
        if length < lo * 0.75 or length > hi * 1.1:
            continue
        start = max(0.0, lines[a]["start"] - 0.15)
        end = min(duration or lines[b]["end"] + 0.3, lines[b]["end"] + 0.3)
        tags = [t if t.startswith("#") else f"#{t}" for t in (sug.hashtags or []) if t.strip()]
        for t in default_tags:
            if t.lower() not in {x.lower() for x in tags}:
                tags.append(t)
        out.append({
            "start": round(start, 2), "end": round(end, 2),
            "score": max(0, min(100, int(sug.score))),
            "title": sug.title.strip()[:100], "description": sug.description.strip(),
            "hook_title": (sug.hook_title or "").strip()[:80],
            "hashtags": [t.replace(" ", "") for t in tags], "hook": sug.hook.strip(),
            "reason": sug.reason.strip(),
        })

    # Keep the best clip when two overlap by more than 30% of the shorter one.
    kept = []
    for c in sorted(out, key=lambda c: -c["score"]):
        ok = True
        for k in kept:
            overlap = min(c["end"], k["end"]) - max(c["start"], k["start"])
            if overlap > 0.3 * min(c["end"] - c["start"], k["end"] - k["start"]):
                ok = False
                break
        if ok and c["score"] >= int(s["min_score"]):
            kept.append(c)
    return sorted(kept[: int(s["clip_count"])], key=lambda c: c["start"])

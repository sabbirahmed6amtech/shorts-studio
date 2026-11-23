"""Ask Gemini for clip suggestions + metadata, then clean up what it returns."""
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
    description: str = Field(description="2-3 sentence YouTube description")
    hashtags: list[str] = Field(description="3-6 relevant hashtags, each starting with #")


class AIError(Exception):
    """A Gemini failure worded for the user."""


def _fmt(t: float) -> str:
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def build_prompt(lines: list[dict], s: dict) -> str:
    transcript = "\n".join(f"L{i} [{_fmt(l['start'])}] {l['text']}" for i, l in enumerate(lines))
    tone = f"\nThe creator wants clips that are: {s['tone']}." if s.get("tone") else ""
    return f"""You are an expert short-form video editor. Below is a transcript of a long video,
split into numbered lines (L0, L1, ...) with timestamps.

Find up to {s['clip_count']} segments that would work as standalone YouTube Shorts.
Each segment must:
- run between {s['clip_min']} and {s['clip_max']} seconds (use the timestamps),
- open with a strong hook in the first line (a question, bold claim, surprise or emotion),
- be a complete thought that makes sense without the rest of the video,
- end on a payoff, not mid-idea,
- not overlap other segments.{tone}

Score each 0-100 for how likely it is to perform well as a Short (hook strength,
clarity without context, emotional or surprising payoff, broad interest).
Write the title, description and hashtags in the same language as the transcript.
Return the segments using line numbers, best first.

TRANSCRIPT:
{transcript}
"""


def suggest(lines: list[dict], s: dict) -> list[ClipSuggestion]:
    if not s.get("gemini_api_key"):
        raise AIError("No Gemini API key. Add one in Settings, then press Run AI again.")
    if not lines:
        raise AIError("No speech was found in this video, so there is nothing for Gemini to read.")
    client = genai.Client(api_key=s["gemini_api_key"])
    try:
        resp = client.models.generate_content(
            model=s["gemini_model"],
            contents=build_prompt(lines, s),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=list[ClipSuggestion],
            ),
        )
    except errors.APIError as e:
        code = getattr(e, "code", None)
        if code == 429:
            raise AIError("Gemini rate limit reached (free tier). Wait a minute, then press Run AI again.")
        if code == 404:
            raise AIError(f"Gemini model '{s['gemini_model']}' was not found. Change the model in Settings.")
        if code in (400, 401, 403) and "key" in str(e).lower():
            raise AIError("Gemini rejected the API key. Check it in Settings.")
        raise AIError(f"Gemini error {code}: {getattr(e, 'message', None) or e}")
    except Exception as e:  # network etc.
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

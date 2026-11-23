"""YouTube: sign in (OAuth), upload a Short, and schedule it with YouTube's own publishAt."""
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import config

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",  # to show which channel is connected
]

# OAuth over plain http is fine here: the redirect goes to this computer (127.0.0.1) only.
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

_pending_flows: dict[str, object] = {}  # state -> Flow (it holds the PKCE verifier)
_lock = threading.Lock()
_channel_cache: dict = {}


class YouTubeError(Exception):
    """A YouTube failure worded for the user."""


# ---------- client file + sign-in ----------

def save_client(raw: bytes) -> None:
    try:
        data = json.loads(raw)
    except ValueError:
        raise YouTubeError("That file isn't valid JSON. Download the OAuth client JSON from Google Cloud again.")
    kind = "installed" if "installed" in data else "web" if "web" in data else None
    if not kind or not data[kind].get("client_id") or not data[kind].get("client_secret"):
        raise YouTubeError("That JSON isn't an OAuth client file. In Google Cloud, create an OAuth client ID "
                           "(type: Desktop app) and download its JSON.")
    config.YT_CLIENT_PATH.write_text(json.dumps(data), encoding="utf-8")


def remove_client() -> None:
    config.YT_CLIENT_PATH.unlink(missing_ok=True)
    disconnect()


def disconnect() -> None:
    config.YT_TOKEN_PATH.unlink(missing_ok=True)
    _channel_cache.clear()


def _flow(redirect_uri: str):
    from google_auth_oauthlib.flow import Flow

    if not config.YT_CLIENT_PATH.exists():
        raise YouTubeError("Upload your Google OAuth client file in Settings first.")
    client = json.loads(config.YT_CLIENT_PATH.read_text(encoding="utf-8"))
    return Flow.from_client_config(client, scopes=SCOPES, redirect_uri=redirect_uri)


def auth_url(redirect_uri: str) -> str:
    flow = _flow(redirect_uri)
    url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    with _lock:
        _pending_flows[state] = flow
    return url


def finish_auth(state: str, full_callback_url: str) -> None:
    with _lock:
        flow = _pending_flows.pop(state, None)
    if flow is None:
        raise YouTubeError("This sign-in link expired. Press Connect YouTube again.")
    try:
        flow.fetch_token(authorization_response=full_callback_url)
    except Exception as e:
        raise YouTubeError(f"Google sign-in failed: {e}")
    creds = flow.credentials
    if not creds.refresh_token:
        raise YouTubeError("Google didn't return a long-lived login. Remove the app's access at "
                           "myaccount.google.com/permissions, then connect again.")
    config.YT_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    _channel_cache.clear()


def _credentials():
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not config.YT_TOKEN_PATH.exists():
        raise YouTubeError("YouTube isn't connected. Connect it in Settings.")
    creds = Credentials.from_authorized_user_file(str(config.YT_TOKEN_PATH), SCOPES)
    if not creds.valid:
        try:
            creds.refresh(Request())
        except RefreshError:
            raise YouTubeError("The YouTube login has expired. Reconnect in Settings. (While your Google "
                               "Cloud app is in Testing mode, Google ends logins after 7 days.)")
        config.YT_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _service():
    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=_credentials(), cache_discovery=False)


def status() -> dict:
    out = {"client": config.YT_CLIENT_PATH.exists(), "connected": config.YT_TOKEN_PATH.exists(),
           "channel": None, "error": None}
    if not out["connected"]:
        return out
    if _channel_cache.get("at", 0) > time.time() - 600:
        out["channel"] = _channel_cache["channel"]
        return out
    try:
        resp = _service().channels().list(part="snippet", mine=True).execute()
        items = resp.get("items") or []
        if not items:
            out["error"] = "This Google account has no YouTube channel yet. Create one on youtube.com first."
        else:
            sn = items[0]["snippet"]
            out["channel"] = {"id": items[0]["id"], "title": sn.get("title"),
                              "thumb": (sn.get("thumbnails", {}).get("default") or {}).get("url")}
            _channel_cache.update(at=time.time(), channel=out["channel"])
    except YouTubeError as e:
        out["error"] = str(e)
    except Exception as e:
        out["error"] = f"Could not reach YouTube: {e}"
    return out


# ---------- scheduling ----------

def next_slots(n: int, taken: list[datetime], s: dict) -> list[datetime]:
    """The next n publish times: daily at the chosen time (this computer's time zone),
    spaced by the gap, after anything already scheduled."""
    local_now = datetime.now().astimezone()
    try:
        hh, mm = (int(x) for x in s["yt_publish_time"].split(":"))
    except ValueError:
        hh, mm = 18, 0
    gap = timedelta(hours=max(1, int(s["yt_gap_hours"])))
    earliest = local_now + timedelta(minutes=30)
    candidate = local_now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    while candidate < earliest:
        candidate += timedelta(days=1)
    future = sorted(t for t in taken if t > local_now)
    if future:
        candidate = max(candidate, future[-1] + gap)
    slots = []
    for _ in range(n):
        slots.append(candidate)
        candidate += gap
    return [t.astimezone(timezone.utc) for t in slots]


# ---------- upload ----------

def build_body(clip: dict, job: dict, s: dict) -> dict:
    tags = [t for t in clip.get("hashtags") or [] if t.strip()]
    if not any(t.lower() == "#shorts" for t in tags):
        tags.append("#shorts")
    title = (clip.get("title") or job.get("title") or "Short").replace("<", "").replace(">", "").strip()[:100]
    desc = (clip.get("description") or "").replace("<", "").replace(">", "").strip()
    desc = (desc + "\n\n" + " ".join(tags)).strip()[:5000]
    keywords, total = [], 0
    for t in tags:  # YouTube caps tags at 500 characters in total
        word = t.lstrip("#")
        if word and total + len(word) + 1 <= 450:
            keywords.append(word)
            total += len(word) + 1
    status = {"selfDeclaredMadeForKids": bool(s["yt_made_for_kids"])}
    if clip.get("yt_publish_at"):
        status["privacyStatus"] = "private"  # YouTube makes it public at publishAt
        status["publishAt"] = clip["yt_publish_at"]
    else:
        status["privacyStatus"] = clip.get("yt_privacy") or s["yt_now_privacy"]
    return {
        "snippet": {"title": title, "description": desc, "tags": keywords, "categoryId": str(s["yt_category"])},
        "status": status,
    }


def _http_error_message(e) -> str:
    try:
        err = json.loads(e.content.decode("utf-8"))["error"]
        reason = (err.get("errors") or [{}])[0].get("reason", "")
        message = err.get("message", "")
    except Exception:
        reason, message = "", str(e)
    if reason in ("quotaExceeded", "rateLimitExceeded"):
        return "YouTube's daily API quota is used up (about 6 uploads a day by default). It resets at midnight Pacific time."
    if reason == "uploadLimitExceeded":
        return "This channel hit YouTube's upload limit. Try again later."
    if reason == "invalidPublishAt":
        return "YouTube rejected the publish time. Pick a time in the future."
    if reason in ("youtubeSignupRequired", "forbidden"):
        return f"YouTube refused the upload: {message}"
    return f"YouTube error: {message or reason}"


def upload(path, clip: dict, job: dict, s: dict, on_progress: Callable[[float], None]) -> str:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    if clip.get("yt_publish_at"):
        when = datetime.fromisoformat(clip["yt_publish_at"].replace("Z", "+00:00"))
        if when < datetime.now(timezone.utc) + timedelta(minutes=2):
            raise YouTubeError("The scheduled time has already passed. Pick a new time and upload again.")
    body = build_body(clip, job, s)
    media = MediaFileUpload(str(path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    try:
        req = _service().videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        retries = 0
        while response is None:
            try:
                prog, response = req.next_chunk()
                retries = 0
            except HttpError as e:
                if e.status_code in (500, 502, 503, 504) and retries < 5:
                    retries += 1
                    time.sleep(2 ** retries)
                    continue
                raise
            if prog:
                on_progress(prog.progress())
    except HttpError as e:
        raise YouTubeError(_http_error_message(e))
    except YouTubeError:
        raise
    except Exception as e:
        raise YouTubeError(f"Upload failed: {e}")
    on_progress(1.0)
    return response["id"]

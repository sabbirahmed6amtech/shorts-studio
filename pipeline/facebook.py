"""Facebook Reels on a Page: connect once, then post or schedule.

Follows Meta's Reels Publishing API: start an upload session, upload the file to
rupload.facebook.com, then finish with PUBLISHED or SCHEDULED.
https://developers.facebook.com/documentation/video-api/guides/reels-publishing
"""
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Callable

import requests

from . import config

GRAPH = "https://graph.facebook.com/v27.0"
TIMEOUT = (20, 120)
MIN_SECONDS, MAX_SECONDS = 3, 90  # Facebook Reels length limits


class FacebookError(Exception):
    """A Facebook failure worded for the user."""


# ---------- stored connection (app id, Page tokens) ----------

def _load() -> dict | None:
    try:
        return json.loads(config.FB_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save(data: dict) -> None:
    config.FB_PATH.write_text(json.dumps(data), encoding="utf-8")


def _page(data: dict | None) -> dict | None:
    if not data:
        return None
    return next((p for p in data.get("pages", []) if p["id"] == data.get("page_id")), None)


def connected() -> bool:
    return _page(_load()) is not None


def status() -> dict:
    data = _load()
    page = _page(data)
    return {
        "connected": page is not None,
        "page": {k: page.get(k) for k in ("id", "name", "picture")} if page else None,
        "pages": [{"id": p["id"], "name": p["name"]} for p in (data or {}).get("pages", [])],
    }


def _error_message(resp) -> str:
    try:
        err = resp.json().get("error") or {}
    except ValueError:
        return f"Facebook error {resp.status_code}: {resp.text[:200]}"
    code, sub, msg = err.get("code"), err.get("error_subcode"), err.get("message", "")
    if code == 190:
        return "The Facebook login has expired or was revoked. Connect Facebook again in Settings."
    if code in (10, 200) or (code == 100 and "permission" in msg.lower()):
        return ("Facebook refused: the app is missing a permission. Reconnect with pages_show_list, "
                "pages_read_engagement and pages_manage_posts. " + msg)
    if code in (4, 17, 32, 613) or "limit" in msg.lower():
        return "Facebook's posting limit was reached (about 30 Reels a day through the API). Try again later."
    if code == 1363128 or sub == 1363128:
        return "Facebook Reels must be 3 to 90 seconds long."
    return f"Facebook error: {msg or resp.text[:200]}"


def _check(resp) -> dict:
    if resp.status_code >= 400:
        raise FacebookError(_error_message(resp))
    try:
        return resp.json()
    except ValueError:
        raise FacebookError(f"Facebook sent an unexpected reply: {resp.text[:200]}")


def connect(app_id: str, app_secret: str, user_token: str) -> dict:
    """Swap a short-lived user token for a long-lived one, then list the Pages it manages.
    Page tokens obtained from a long-lived user token don't expire."""
    app_id, app_secret, user_token = app_id.strip(), app_secret.strip(), user_token.strip()
    if not (app_id and app_secret and user_token):
        raise FacebookError("Fill in the App ID, App Secret and access token.")
    try:
        long = _check(requests.get(f"{GRAPH}/oauth/access_token", params={
            "grant_type": "fb_exchange_token", "client_id": app_id,
            "client_secret": app_secret, "fb_exchange_token": user_token}, timeout=TIMEOUT))["access_token"]
        pages, url, params = [], f"{GRAPH}/me/accounts", {
            "fields": "id,name,access_token,tasks,picture{url}", "limit": 100, "access_token": long}
        for _ in range(5):
            data = _check(requests.get(url, params=params, timeout=TIMEOUT))
            for p in data.get("data", []):
                if "CREATE_CONTENT" in (p.get("tasks") or ["CREATE_CONTENT"]):
                    pages.append({"id": p["id"], "name": p["name"], "token": p["access_token"],
                                  "picture": ((p.get("picture") or {}).get("data") or {}).get("url")})
            url, params = (data.get("paging") or {}).get("next"), None
            if not url:
                break
    except requests.RequestException as e:
        raise FacebookError(f"Could not reach Facebook: {e}")
    if not pages:
        raise FacebookError("No Pages found that you can post to. In Graph API Explorer, choose your Page when "
                            "asked and grant pages_show_list, pages_read_engagement and pages_manage_posts.")
    old = _load() or {}
    keep = old.get("page_id") if any(p["id"] == old.get("page_id") for p in pages) else pages[0]["id"]
    _save({"app_id": app_id, "pages": pages, "page_id": keep})
    return status()


def select_page(page_id: str) -> dict:
    data = _load()
    if not data or not any(p["id"] == page_id for p in data.get("pages", [])):
        raise FacebookError("That Page isn't in your connected Pages.")
    data["page_id"] = page_id
    _save(data)
    return status()


def disconnect() -> None:
    config.FB_PATH.unlink(missing_ok=True)


# ---------- posting ----------

def check_schedule(publish_at: datetime) -> None:
    now = datetime.now(timezone.utc)
    if publish_at < now + timedelta(minutes=10):
        raise FacebookError("Facebook needs the publish time to be at least 10 minutes from now.")
    if publish_at > now + timedelta(days=29):
        raise FacebookError("Facebook can only schedule Reels up to 29 days ahead.")


def check_length(seconds: float) -> None:
    if not MIN_SECONDS <= seconds <= MAX_SECONDS + 0.5:
        raise FacebookError(f"Facebook Reels must be {MIN_SECONDS}–{MAX_SECONDS} seconds; this clip is "
                            f"{seconds:.0f}s. Trim it, or post it to YouTube only.")


def build_text(clip: dict, job: dict) -> tuple[str, str]:
    title = (clip.get("title") or job.get("title") or "").strip()[:255]
    tags = " ".join(t for t in clip.get("hashtags") or [] if t.strip())
    desc = "\n\n".join(x for x in (title, (clip.get("description") or "").strip(), tags) if x)
    return title, desc[:2200]


class _ProgressFile:
    """File wrapper that reports how much has been read (so: uploaded)."""

    def __init__(self, path, on_progress):
        self.f = open(path, "rb")
        self.size = os.path.getsize(path)
        self.done = 0
        self.on_progress = on_progress

    def __len__(self):
        return self.size

    def read(self, n=-1):
        chunk = self.f.read(n if n and n > 0 else 1024 * 1024)
        self.done += len(chunk)
        self.on_progress(min(0.99, self.done / max(1, self.size)))
        return chunk

    def close(self):
        self.f.close()


def upload(path, clip: dict, job: dict, on_progress: Callable[[float], None]) -> str:
    page = _page(_load())
    if not page:
        raise FacebookError("Facebook isn't connected. Connect a Page in Settings.")
    check_length(clip["end"] - clip["start"])
    when = None
    if clip.get("fb_publish_at"):
        when = datetime.fromisoformat(clip["fb_publish_at"].replace("Z", "+00:00"))
        if when < datetime.now(timezone.utc) + timedelta(minutes=2):
            raise FacebookError("The scheduled time has already passed. Pick a new time and post again.")
    token, page_id = page["token"], page["id"]
    title, desc = build_text(clip, job)
    try:
        start = _check(requests.post(f"{GRAPH}/{page_id}/video_reels",
                                     data={"upload_phase": "start", "access_token": token}, timeout=TIMEOUT))
        video_id = start["video_id"]
        upload_url = start.get("upload_url") or f"https://rupload.facebook.com/video-upload/v27.0/{video_id}"
        body = _ProgressFile(path, on_progress)
        try:
            up = _check(requests.post(upload_url, data=body, timeout=(20, 1800), headers={
                "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(body.size),
                "Content-Type": "application/octet-stream"}))
        finally:
            body.close()
        if up.get("success") is False:
            raise FacebookError(f"Facebook didn't accept the upload: {up}")
        params = {"access_token": token, "video_id": video_id, "upload_phase": "finish",
                  "video_state": "SCHEDULED" if when else "PUBLISHED", "description": desc}
        if title:
            params["title"] = title
        if when:
            params["scheduled_publish_time"] = int(when.timestamp())
        fin = _check(requests.post(f"{GRAPH}/{page_id}/video_reels", params=params, timeout=TIMEOUT))
        if fin.get("success") is False:
            raise FacebookError(f"Facebook didn't publish the Reel: {fin}")
    except requests.RequestException as e:
        raise FacebookError(f"Could not reach Facebook: {e}")
    on_progress(1.0)
    return video_id

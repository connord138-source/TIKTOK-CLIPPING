"""Upload-Post: the posting service that publishes clips publicly, with captions, to TikTok,
Instagram Reels and YouTube Shorts. (TikTok will not approve a personal uploader app, so
public posting has to go through a service whose TikTok app is already approved.)

An Upload-Post "profile" holds one account per platform. Each profile is one account record
here (platform "uploadpost"): a clip assigned to it goes to every platform it has connected.

Nothing is posted unless the user turns on "Post automatically" for a profile, or clicks
"Post now" on a clip.

API facts (docs.upload-post.com, read 2026-11-25):
  auth      Authorization: Apikey <key>          base https://api.upload-post.com
  upload    POST /api/upload  multipart: user, platform[], video, title, scheduled_date, ...
            200 sync results | 200 {request_id} when async | 202 {job_id} when scheduled
  status    GET /api/uploadposts/status?request_id=|job_id=
  cancel    DELETE /api/uploadposts/schedule/<job_id>
  profiles  GET /api/uploadposts/users
  caps      per account per 24h: TikTok 15, YouTube 30, Instagram 50
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import accounts
from .core import ROOT, Store, hours_since, load_config, log, now_iso, parse_iso

API = os.environ.get("UPLOADPOST_API_BASE", "https://api.upload-post.com")   # override is for local testing only
PLATFORMS = ("tiktok", "instagram", "youtube")
_lock = threading.Lock()

ERRORS = {
    401: "Upload-Post rejected the API key. Paste a fresh key in Connections.",
    403: "Upload-Post refused this upload. TikTok needs the Basic plan or higher, and the plan's profile limit may be reached.",
    404: "Upload-Post does not know this profile any more. Click Refresh profiles in Connections.",
    429: "Upload-Post says the plan's upload limit is reached.",
}


class UploadPostError(RuntimeError):
    def __init__(self, status: int, message: str = ""):
        self.status = status
        super().__init__(ERRORS.get(status) or f"Upload-Post error {status}: {message}".strip())


def api_key() -> str | None:
    return os.environ.get("UPLOADPOST_API_KEY") or None


# ---------------------------------------------------------------- http (tests patch API to a local server)
def _request(method: str, path: str, *, fields: list | None = None, file: tuple | None = None,
             body: dict | None = None, headers: dict | None = None, timeout: int = 600) -> tuple[int, dict]:
    """-> (status, json). Never raises on HTTP status."""
    if not api_key():
        raise UploadPostError(401)
    hdrs = {"Authorization": f"Apikey {api_key()}", **(headers or {})}
    data = None
    if fields is not None:
        boundary = "clipfarm" + uuid.uuid4().hex
        parts = []
        for name, value in fields:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8"))
        if file:
            fname, path_, ctype = file
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="video"; filename="{fname}"\r\n'
                         f"Content-Type: {ctype}\r\n\r\n".encode("utf-8") + Path(path_).read_bytes() + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        data = b"".join(parts)
        hdrs["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    try:
        return status, json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return status, {"message": raw[:200].decode("utf-8", "replace")}


def _ok(status: int, d: dict) -> dict:
    if status >= 400:
        raise UploadPostError(status, str(d.get("message") or d.get("error") or ""))
    return d


# ---------------------------------------------------------------- profiles -> account records
def _connected(social) -> dict:
    """{platform: {"handle", "reauth"}} for the platforms a profile has connected."""
    out = {}
    for p in PLATFORMS:
        acc = (social or {}).get(p)
        if not acc:
            continue
        acc = acc if isinstance(acc, dict) else {}
        out[p] = {"handle": str(acc.get("handle") or acc.get("display_name") or acc.get("username") or "").lstrip("@"),
                  "reauth": bool(acc.get("reauth_required"))}
    return out


def sync_profiles() -> list[dict]:
    """Read the profiles from Upload-Post and keep one account record per profile. Settings the
    user chose here (niches, posts a day, the automatic switch) are kept."""
    status, d = _request("GET", "/api/uploadposts/users", timeout=60)
    profiles = _ok(status, d).get("profiles") or []
    seen = set()
    for pr in profiles:
        username = pr.get("username")
        if not username:
            continue
        aid = accounts.account_id("uploadpost", username.lower())
        seen.add(aid)
        plats = _connected(pr.get("social_accounts"))
        accounts.upsert({"id": aid, "platform": "uploadpost", "via": "uploadpost", "profile": username,
                         "name": pr.get("display_name") or username, "platforms": plats, "missing": False,
                         "handle": (plats.get("tiktok") or {}).get("handle") or ""})
        if accounts.get(aid).get("auto_post") is None:
            accounts.upsert({"id": aid, "auto_post": False})
    for a in accounts.all_accounts("uploadpost"):
        if a["id"] not in seen and not a.get("missing"):
            accounts.upsert({"id": a["id"], "missing": True})
    log(f"upload-post: {len(seen)} profile(s)")
    return accounts.all_accounts("uploadpost")


def summary() -> dict:
    accts = accounts.all_accounts("uploadpost")
    return {"configured": bool(api_key()), "accounts": accts,
            "ready": any(a.get("platforms") and not a.get("missing") and a.get("enabled", True) for a in accts)}


# ---------------------------------------------------------------- posting
def _targets(acct: dict) -> list[str]:
    off = set(acct.get("platforms_off") or [])
    return [p for p in PLATFORMS if p in (acct.get("platforms") or {}) and p not in off]


def _fields(clip: dict, acct: dict, when_utc: datetime | None) -> list:
    caption = (clip.get("caption") or clip.get("hook") or "").strip()
    hook = (clip.get("hook") or (caption.splitlines()[0] if caption else "") or "Clip").strip()
    targets = _targets(acct)
    f = [("user", acct["profile"]), ("title", caption[:2200]), ("external_id", clip["id"])]
    f += [("platform[]", p) for p in targets]
    if "tiktok" in targets:
        f += [("post_mode", "DIRECT_POST"), ("privacy_level", acct.get("privacy") or "PUBLIC_TO_EVERYONE"),
              ("is_aigc", "false")]
    if "youtube" in targets:
        tags = [t.lstrip("#") for t in (clip.get("hashtags") or [])][:10]
        f += [("youtube_title", hook[:95]), ("youtube_description", caption[:4500]), ("privacyStatus", "public"),
              ("selfDeclaredMadeForKids", "false")]
        f += [("tags[]", t) for t in tags]
        if (clip.get("niche") or "gta6") == "gta6":
            f.append(("categoryId", "20"))  # Gaming
    if "instagram" in targets:
        f += [("media_type", "REELS"), ("share_to_feed", "true")]
    if when_utc:
        f.append(("scheduled_date", when_utc.strftime("%Y-%m-%dT%H:%M:%SZ")))
    else:
        f.append(("async_upload", "true"))
    return f


def _platform_results(results) -> dict:
    """Normalise both response shapes to {platform: {"success", "url", "message"}}."""
    out = {}
    items = results.items() if isinstance(results, dict) else [((r or {}).get("platform"), r) for r in (results or [])]
    for name, r in items:
        if not name or not isinstance(r, dict) or r.get("skipped"):
            continue
        out[name] = {"success": bool(r.get("success")), "url": r.get("url") or r.get("post_url"),
                     "message": str(r.get("error") or r.get("message") or "")[:200]}
    return out


def post_clip(clip_id: str, when_local: datetime | None = None) -> dict:
    """Send one approved clip to its Upload-Post profile: now, or at `when_local` (a slot time).
    Marks it `scheduled`; sync_posts() later marks it `posted` with the links."""
    with _lock:
        clip = Store.get(Store.clips, clip_id)
        if not clip:
            raise KeyError(clip_id)
        try:
            if clip.get("status") != "approved":
                raise UploadPostError(0, f"{clip_id} is {clip.get('status')}; only approved clips are posted")
            acct = accounts.get(clip.get("account_id"))
            if not acct or acct.get("via") != "uploadpost" or acct.get("missing"):
                raise UploadPostError(0, f"{clip_id} is not assigned to an Upload-Post profile")
            if not _targets(acct):
                raise UploadPostError(0, f"the profile {acct.get('name')} has no TikTok, Instagram or YouTube account connected")
            path = (ROOT / (clip.get("file") or "")).resolve()
            if not clip.get("file") or not path.is_file():
                raise UploadPostError(0, f"clip file not found: {path}")
            when_utc = when_local.astimezone(timezone.utc) if when_local else None
            if when_utc and when_utc < datetime.now(timezone.utc) + timedelta(minutes=3):
                when_utc = None   # too close to schedule: post now
            attempt = int(clip.get("post_attempts") or 0) + 1
            status, d = _request("POST", "/api/upload", fields=_fields(clip, acct, when_utc),
                                 file=(f"{clip_id}.mp4", path, "video/mp4"),
                                 headers={"Idempotency-Key": f"{clip_id}-{acct['id']}-{attempt}"})
            d = _ok(status, d)
            if d.get("success") is False:
                raise UploadPostError(status, str(d.get("message") or d.get("error") or "upload refused"))
        except Exception as e:  # noqa: BLE001
            Store.update(Store.clips, clip_id, sending=False, draft_error=str(e),
                         post_attempts=int((Store.get(Store.clips, clip_id) or {}).get("post_attempts") or 0) + 1)
            log(f"upload-post: {clip_id} not sent: {e}")
            raise
        post = {"via": "uploadpost", "profile": acct["profile"], "platforms": _targets(acct), "sent_at": now_iso(),
                "job_id": d.get("job_id"), "request_id": d.get("request_id"),
                "scheduled_for": when_utc.strftime("%Y-%m-%dT%H:%M:%SZ") if when_utc else None}
        Store.update(Store.clips, clip_id, status="scheduled", sending=False, draft_error=None, post=post,
                     post_attempts=attempt)
        if d.get("results") and not post["job_id"] and not post["request_id"]:
            _finish(Store.get(Store.clips, clip_id), _platform_results(d["results"]))   # answered at once
        log(f"upload-post: {clip_id} -> {acct.get('name')} ({', '.join(post['platforms'])}) "
            + (f"scheduled for {post['scheduled_for']}" if when_utc else "publishing now"))
        return {"clip": clip_id, **post}


def _finish(clip: dict, results: dict) -> str:
    """Apply final per-platform results to a clip. -> 'posted' | 'failed'"""
    good = {p: r for p, r in results.items() if r["success"]}
    bad = {p: r for p, r in results.items() if not r["success"]}
    post = {**(clip.get("post") or {}), "results": results, "finished_at": now_iso()}
    if not good:
        why = "; ".join(f"{p}: {r['message'] or 'failed'}" for p, r in bad.items()) or "no platform accepted it"
        Store.update(Store.clips, clip["id"], status="approved", post=post, draft_error=f"Not posted. {why}")
        return "failed"
    tt = (good.get("tiktok") or {}).get("url") or ""
    m = re.search(r"/video/(\d{8,})", tt)
    Store.update(Store.clips, clip["id"], status="posted", posted_at=now_iso(), post=post,
                 tiktok_url=tt or clip.get("tiktok_url"), tiktok_id=m.group(1) if m else clip.get("tiktok_id"),
                 draft_error=("Posted, but not everywhere. " + "; ".join(f"{p}: {r['message'] or 'failed'}" for p, r in bad.items())) if bad else None)
    return "posted"


def _scheduled_clips() -> list[dict]:
    return [c for c in Store.all(Store.clips)
            if c.get("status") == "scheduled" and (c.get("post") or {}).get("via") == "uploadpost"]


def sync_posts() -> dict:
    """Ask Upload-Post how each sent clip went; mark clips posted (with links) or failed."""
    posted = failed = 0
    for c in _scheduled_clips():
        post = c.get("post") or {}
        due = parse_iso(post.get("scheduled_for"))
        if due and due > datetime.now(timezone.utc) + timedelta(minutes=1):
            continue   # not time yet
        key = "job_id" if post.get("job_id") else "request_id"
        if not post.get(key):
            continue
        try:
            status, d = _request("GET", f"/api/uploadposts/status?{key}=" + urllib.parse.quote(str(post[key])), timeout=60)
        except UploadPostError:
            break
        state = d.get("status")
        if status == 404 or state == "not_found":
            if (hours_since(post.get("sent_at")) or 0) > 26:
                Store.update(Store.clips, c["id"], status="approved", draft_error="Upload-Post lost track of this post. Send it again.")
                failed += 1
            continue
        if status >= 400 or state not in ("completed", "failed"):
            continue
        results = _platform_results(d.get("results"))
        if state == "failed" and not results:
            results = {p: {"success": False, "url": None, "message": str(d.get("message") or "failed")} for p in post.get("platforms") or []}
        if _finish(c, results) == "posted":
            posted += 1
        else:
            failed += 1
    return {"posted": posted, "failed": failed}


def cancel(clip_id: str) -> dict:
    """Take a clip back before it is published (only works while Upload-Post still holds it)."""
    clip = Store.get(Store.clips, clip_id)
    post = (clip or {}).get("post") or {}
    if not clip or clip.get("status") != "scheduled":
        raise UploadPostError(0, "this clip is not waiting to be posted")
    if not post.get("job_id"):
        raise UploadPostError(0, "this clip is already being published and cannot be taken back")
    status, d = _request("DELETE", "/api/uploadposts/schedule/" + urllib.parse.quote(str(post["job_id"])), timeout=60)
    _ok(status, d)
    return Store.update(Store.clips, clip_id, status="approved", post=None, draft_error=None)


def post_ready(max_clips: int | None = None, only_auto: bool = True) -> dict:
    """For each profile with automatic posting on: schedule today's assigned clips at their slot
    times (and post any whose slot has just arrived)."""
    from . import planner
    cfg = load_config()
    tz = planner._tz(cfg)
    now_local = datetime.now(tz)
    p = planner.plan()
    sent, errors = [], []
    for ap in p["accounts"]:
        acct = accounts.get(ap["id"]) if ap["id"] else None
        if not acct or acct.get("via") != "uploadpost" or (only_auto and not acct.get("auto_post")):
            continue
        for b in ap["slots"]:
            if b["state"] != "assigned" or b.get("queued"):
                continue
            if max_clips is not None and len(sent) + len(errors) >= max_clips:
                break
            h, m = map(int, b["time"].split(":"))
            at = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
            try:
                sent.append(post_clip(b["clip_id"], at)["clip"])
                time.sleep(2)
            except Exception as e:  # noqa: BLE001
                errors.append({"clip": b["clip_id"], "error": str(e)})
                if isinstance(e, UploadPostError) and e.status in ERRORS:
                    break   # account-level problem: stop for this profile
    return {"sent": sent, "errors": errors}


"""TikTok API client: login (desktop OAuth + PKCE), tokens, and upload-to-inbox ("drafts").

Only the inbox endpoint is used: the video lands in the user's TikTok inbox/drafts and the
user finishes and posts it in the TikTok app. The direct-post endpoint is deliberately not
implemented (CLAUDE.md hard rule 1).

Facts from TikTok's docs (checked 2026-11-18):
  init    POST /v2/post/publish/inbox/video/init/   scope video.upload, 6 requests/min
  upload  PUT upload_url, Content-Range, 201 = done, 206 = more chunks; url valid 1 hour
  status  POST /v2/post/publish/status/fetch/       SEND_TO_USER_INBOX | PUBLISH_COMPLETE | FAILED
  cap     at most 5 pending (unposted) inbox uploads per 24 hours
  tokens  access 2 hours, refresh 180 days, refresh token rotates on every refresh
  PKCE    code_challenge = HEX sha256(code_verifier)   (TikTok-specific, not base64url)
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import accounts
from .core import ROOT, Store, hours_since, load_config, log, now_iso

API = "https://open.tiktokapis.com/v2/"
AUTHORIZE = "https://www.tiktok.com/v2/auth/authorize/"
BASE_SCOPES = ["user.info.basic", "video.upload"]          # what drafts need
STATS_SCOPES = ["user.info.stats", "video.list"]           # optional: analytics via the API
SINGLE_PUT_MAX = 64_000_000                                 # larger files must be chunked
CHUNK = 10_000_000
PENDING_CAP = 5

_send_lock = threading.Lock()   # one upload at a time (init is limited to 6/min)
_pending_auth: dict[str, str] = {}  # state -> code_verifier

ERRORS = {
    "access_token_invalid": "TikTok login expired. Open Connections and click Connect TikTok again.",
    "scope_not_authorized": "TikTok refused the upload: your TikTok app does not have the video.upload "
                            "permission for this account yet (add Content Posting API to the app, add your "
                            "account as a sandbox target user or get the app approved, then reconnect).",
    "spam_risk_too_many_pending_share": "TikTok allows 5 unposted drafts per 24 hours. Post or delete "
                                        "some drafts in TikTok, then send again.",
    "spam_risk_user_banned_from_posting": "TikTok says this account is currently blocked from posting.",
    "rate_limit_exceeded": "TikTok rate limit hit. Wait a minute and send again.",
}


class TikTokError(RuntimeError):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(ERRORS.get(code) or f"TikTok error {code}: {message}".strip())


# ---------------------------------------------------------------- http (single choke point; tests patch this)
def _http(method: str, url: str, headers: dict, data: bytes | None = None, timeout: int = 120):
    """-> (status, response_headers, body_bytes). Never raises on HTTP status."""
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()


def _json_body(body: bytes) -> dict:
    try:
        return json.loads(body or b"{}")
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------- app credentials + login
def client_key() -> str | None:
    return os.environ.get("TIKTOK_CLIENT_KEY") or None


def scopes() -> list[str]:
    extra = STATS_SCOPES if load_config().get("tiktok", {}).get("request_stats_scopes") else []
    return BASE_SCOPES + extra


def default_redirect_uri(port: int) -> str:
    return f"http://127.0.0.1:{port}/auth/tiktok/callback/"


def redirect_uri(port: int) -> str:
    """Where TikTok sends the browser after login. Default is the local dashboard (TikTok's
    Desktop rule: localhost/127.0.0.1 + port). TikTok's portal can refuse local addresses; then
    set tiktok.redirect_uri (Connections tab) to an https page that forwards to the dashboard,
    e.g. the GitHub Pages copy of docs/tiktok-callback/."""
    return (os.environ.get("TIKTOK_REDIRECT_URI")
            or (load_config().get("tiktok", {}).get("redirect_uri") or "").strip()
            or default_redirect_uri(port))


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)[:64]  # 43-128 chars from [A-Za-z0-9-._~]
    return verifier, hashlib.sha256(verifier.encode()).hexdigest()


def authorize_url(port: int) -> str:
    if not client_key():
        raise TikTokError("not_configured", "save your TikTok client key and secret first")
    state = secrets.token_urlsafe(16)
    uri = redirect_uri(port)
    params = {"client_key": client_key(), "scope": ",".join(scopes()), "response_type": "code",
              "redirect_uri": uri, "state": state}
    _pending_auth.clear()
    if uri.startswith("https://"):   # TikTok "Web" login: no PKCE in its spec
        _pending_auth[state] = ""
        params["disable_auto_auth"] = 1   # always show TikTok's screen, so another account can be chosen
    else:                            # TikTok "Desktop" login: PKCE required
        verifier, challenge = pkce_pair()
        _pending_auth[state] = verifier
        params.update(code_challenge=challenge, code_challenge_method="S256")
    return AUTHORIZE + "?" + urllib.parse.urlencode(params)


def _token_request(fields: dict, aid: str | None = None) -> dict:
    body = urllib.parse.urlencode({"client_key": client_key() or "",
                                   "client_secret": os.environ.get("TIKTOK_CLIENT_SECRET", ""), **fields}).encode()
    status, _, raw = _http("POST", API + "oauth/token/", {"Content-Type": "application/x-www-form-urlencoded"}, body, 30)
    tok = _json_body(raw)
    if "access_token" not in tok:
        raise TikTokError(tok.get("error") or f"http_{status}", tok.get("error_description") or "login failed")
    tok["obtained_at"] = time.time()
    if aid:
        tok.setdefault("open_id", (accounts.token(aid) or {}).get("open_id"))
        accounts.set_token(aid, tok)  # refresh tokens rotate: always keep the newest
    return tok


def finish_login(code: str, state: str, port: int) -> dict:
    """Completes a login and adds (or refreshes) that TikTok account. Returns the account."""
    if state not in _pending_auth or not code:
        raise TikTokError("state_mismatch", "start again from Connections > Connect TikTok")
    verifier = _pending_auth.pop(state)
    fields = {"code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri(port)}
    if verifier:
        fields["code_verifier"] = verifier
    tok = _token_request(fields)
    if not tok.get("open_id"):
        raise TikTokError("no_open_id", "TikTok did not say which account logged in")
    aid = accounts.account_id("tiktok", tok["open_id"])
    accounts.set_token(aid, tok)
    existing = accounts.get(aid)
    name = (existing or {}).get("name")
    try:
        status, _, raw = _http("GET", API + "user/info/?fields=open_id,display_name",
                               {"Authorization": f"Bearer {tok['access_token']}"}, None, 30)
        name = (_json_body(raw).get("data") or {}).get("user", {}).get("display_name") or name
    except Exception:  # noqa: BLE001 - the name is cosmetic
        pass
    first = not accounts.all_accounts("tiktok")
    acct = {"id": aid, "platform": "tiktok", "name": name or "TikTok account"}
    if not existing and first:
        acct["handle"] = load_config().get("account_handle") or ""
    return accounts.upsert(acct)


def disconnect(aid: str) -> None:
    accounts.remove(aid)


def token(aid: str | None = None) -> dict | None:
    """The login for one account; with no id, the first connected TikTok account's."""
    if aid:
        return accounts.token(aid)
    first = next(iter(accounts.active("tiktok")), None)
    return accounts.token(first["id"]) if first else None


def granted_scopes(aid: str | None = None) -> list[str]:
    return [s for s in ((token(aid) or {}).get("scope") or "").split(",") if s]


def access_token(aid: str) -> str:
    tok = accounts.token(aid)
    if not tok:
        raise TikTokError("access_token_invalid")
    if time.time() > tok["obtained_at"] + tok.get("expires_in", 7200) - 300:
        tok = _token_request({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]}, aid)
    return tok["access_token"]


def account_status(a: dict) -> dict:
    granted = granted_scopes(a["id"])
    return {**a, "connected": bool(accounts.token(a["id"])), "can_upload": "video.upload" in granted,
            "can_read_stats": "video.list" in granted, "pending_24h": pending_count(a["id"])}


def status_summary(port: int) -> dict:
    accts = [account_status(a) for a in accounts.all_accounts("tiktok")]
    live = [a for a in accts if a["connected"] and a.get("enabled", True)]
    return {"configured": bool(client_key() and os.environ.get("TIKTOK_CLIENT_SECRET")),
            "accounts": accts, "connected": bool(live), "can_upload": any(a["can_upload"] for a in live),
            "can_read_stats": any(a["can_read_stats"] for a in live), "redirect_uri": redirect_uri(port),
            "default_redirect_uri": default_redirect_uri(port),
            "pending_24h": sum(a["pending_24h"] for a in live), "pending_cap": PENDING_CAP * max(len(live), 1),
            "pending_cap_per_account": PENDING_CAP}


# ---------------------------------------------------------------- API calls
def _api(path: str, body: dict, aid: str) -> dict:
    status, _, raw = _http("POST", API + path, {"Authorization": f"Bearer {access_token(aid)}",
                                                 "Content-Type": "application/json; charset=UTF-8"},
                           json.dumps(body).encode(), 60)
    d = _json_body(raw)
    err = d.get("error") or {}
    if err.get("code", "ok") != "ok" or status >= 400:
        raise TikTokError(err.get("code") or f"http_{status}", err.get("message", ""))
    return d.get("data") or {}


def chunk_plan(size: int) -> tuple[int, int]:
    """-> (chunk_size, total_chunk_count). The final chunk absorbs the remainder."""
    if size <= SINGLE_PUT_MAX:
        return size, 1
    return CHUNK, size // CHUNK


def upload_file(upload_url: str, path: Path, size: int, chunk_size: int, count: int) -> None:
    with open(path, "rb") as f:
        for i in range(count):
            first = i * chunk_size
            last = size - 1 if i == count - 1 else first + chunk_size - 1
            f.seek(first)
            data = f.read(last - first + 1)
            for attempt in range(3):
                status, _, raw = _http("PUT", upload_url, {
                    "Content-Type": "video/mp4", "Content-Length": str(len(data)),
                    "Content-Range": f"bytes {first}-{last}/{size}"}, data, 600)
                if status in (201, 206):
                    break
                if status < 500 or attempt == 2:
                    raise TikTokError(f"upload_http_{status}", raw[:200].decode("utf-8", "replace"))
                time.sleep(2 * (attempt + 1))


def fetch_status(publish_id: str, aid: str) -> dict:
    return _api("post/publish/status/fetch/", {"publish_id": publish_id}, aid)


# ---------------------------------------------------------------- farm integration
def _api_drafts(aid: str | None = None) -> list[dict]:
    return [c for c in Store.all(Store.clips)
            if c.get("status") == "drafted" and (c.get("draft") or {}).get("via") == "tiktok_api"
            and (aid is None or c.get("account_id") == aid)]


def pending_count(aid: str | None = None) -> int:
    """Our own count of unposted API drafts sent in the last 24h (TikTok caps these at 5 per account)."""
    return sum(1 for c in _api_drafts(aid) if (hours_since((c.get("draft") or {}).get("sent_at")) or 99) < 24)


def _uploaders() -> list[dict]:
    return [a for a in accounts.active("tiktok") if "video.upload" in granted_scopes(a["id"])]


def _account_for(clip: dict) -> dict:
    """The account a clip is sent to: the one the planner assigned, else the best fit now."""
    ups = _uploaders()
    if not ups:
        raise TikTokError("access_token_invalid")
    if clip.get("account_id"):
        a = next((x for x in ups if x["id"] == clip["account_id"]), None)
        if a:
            return a
    fits = [a for a in ups if accounts.takes(a, clip)] or ups
    return min(fits, key=lambda a: pending_count(a["id"]))


def send_clip(clip_id: str) -> dict:
    """Upload one approved clip to its account's TikTok inbox. Marks it `drafted` on success;
    on failure it stays `approved` with `draft_error` set."""
    with _send_lock:
        clip = Store.get(Store.clips, clip_id)
        if not clip:
            raise KeyError(clip_id)
        try:
            if clip.get("status") != "approved":
                raise TikTokError("not_approved", f"{clip_id} is {clip.get('status')}; only approved clips are sent")
            path = (ROOT / (clip.get("file") or "")).resolve()
            if not clip.get("file") or not path.is_file():
                raise TikTokError("file_missing", f"clip file not found: {path}")
            acct = _account_for(clip)
            aid = acct["id"]
            size = path.stat().st_size
            chunk_size, count = chunk_plan(size)
            data = _api("post/publish/inbox/video/init/", {"source_info": {
                "source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk_size, "total_chunk_count": count}}, aid)
            publish_id = data["publish_id"]
            log(f"tiktok: uploading {clip_id} to {acct.get('name')} ({size / 1e6:.1f} MB, {count} chunk(s))")
            upload_file(data["upload_url"], path, size, chunk_size, count)
            state = "PROCESSING_UPLOAD"
            for _ in range(20):  # status endpoint: 30 requests/min
                time.sleep(3)
                st = fetch_status(publish_id, aid)
                state = st.get("status") or state
                if state == "FAILED":
                    raise TikTokError(st.get("fail_reason") or "failed", "TikTok rejected the video")
                if state in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
                    break
        except Exception as e:  # noqa: BLE001
            Store.update(Store.clips, clip_id, sending=False, draft_error=str(e))
            log(f"tiktok: {clip_id} not sent: {e}")
            raise
        draft = {"via": "tiktok_api", "publish_id": publish_id, "state": state, "sent_at": now_iso()}
        Store.update(Store.clips, clip_id, status="drafted", sending=False, draft=draft, draft_error=None,
                     account_id=aid)
        log(f"tiktok: {clip_id} is in the TikTok inbox of {acct.get('name')} ({state})")
        return {"clip": clip_id, "account": aid, **draft}


def send_ready(max_clips: int | None = None) -> dict:
    """Send approved clips to each account in slot order, up to that account's open slots and
    the room left under TikTok's cap of 5 unposted drafts per account."""
    from . import planner
    p = planner.plan()
    sent, errors, n = [], [], 0
    for ap in p["accounts"]:
        aid = ap["id"]
        if not aid or not any(a["id"] == aid for a in _uploaders()):
            continue
        queue = [b["clip_id"] for b in ap["slots"] if b["state"] == "assigned" and not b.get("in_drafts")]
        room = max(0, PENDING_CAP - pending_count(aid))
        for cid in queue[:room]:
            if max_clips is not None and n >= max_clips:
                break
            if n:
                time.sleep(10)  # keep well under 6 inits/min
            n += 1
            try:
                sent.append(send_clip(cid)["clip"])
            except Exception as e:  # noqa: BLE001
                errors.append({"clip": cid, "error": str(e)})
                if isinstance(e, TikTokError) and e.code in ERRORS:
                    break  # account-level problem: the rest for this account would fail the same way
    return {"sent": sent, "errors": errors}


def sync_drafts() -> dict:
    """Refresh API drafts: mark clips posted once the user publishes them from TikTok."""
    posted = failed = 0
    dead: set = set()
    for c in _api_drafts():
        d = c.get("draft") or {}
        aid = c.get("account_id")
        if not d.get("publish_id") or not aid or aid in dead or not accounts.token(aid):
            continue
        try:
            st = fetch_status(d["publish_id"], aid)
        except TikTokError as e:
            log(f"tiktok sync {c['id']}: {e}")
            if e.code in ("access_token_invalid", "rate_limit_exceeded"):
                dead.add(aid)
            continue
        state = st.get("status")
        if state == "PUBLISH_COMPLETE":
            ids = st.get("publicaly_available_post_id") or []  # (sic) TikTok's spelling
            tid = str(ids[0]) if ids else None
            handle = (accounts.get(aid) or {}).get("handle")
            url = f"https://www.tiktok.com/@{handle}/video/{tid}" if tid and handle else None
            Store.update(Store.clips, c["id"], status="posted", posted_at=now_iso(), tiktok_id=tid,
                         tiktok_url=url, draft={**d, "state": state})
            posted += 1
        elif state == "FAILED":
            Store.update(Store.clips, c["id"], status="approved", draft={**d, "state": state},
                         draft_error=f"TikTok rejected the video: {st.get('fail_reason')}")
            failed += 1
        elif state and state != d.get("state"):
            Store.update(Store.clips, c["id"], draft={**d, "state": state})
    return {"posted": posted, "failed": failed}

"""Accounts: the social profiles the farm delivers to. Several per platform are supported,
each with its own login, niches, posts per day and delivery mode.

  mode "drafts"  the clip is sent to the account's TikTok inbox; the user posts it.
  mode "post"    the farm posts it at the slot time, with the caption. The user turns this on
                 per account; nothing posts by default.

Settings live under `accounts` in config/account.json (written by the dashboard); logins live
in data/secrets/tokens.json (gitignored).
"""
from __future__ import annotations

import hashlib

from .core import SECRETS_DIR, Store, _lock, load_config, read_json, save_config, write_json

TOKENS_FILE = SECRETS_DIR / "tokens.json"
LEGACY_TIKTOK_TOKEN = SECRETS_DIR / "tiktok_token.json"
MODES = ("drafts", "post")
PRIVACY = ("PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY")
MAX_PER_DAY = 15  # TikTok's own ceiling for automatic posts per account is "typically around 15"


def account_id(platform: str, remote_id: str) -> str:
    return {"tiktok": "tt", "youtube": "yt", "instagram": "ig"}.get(platform, platform[:2]) + "_" + \
        hashlib.sha1(remote_id.encode()).hexdigest()[:8]


def _migrate() -> None:
    """One TikTok login used to live in tiktok_token.json with no account record."""
    if not LEGACY_TIKTOK_TOKEN.exists():
        return
    tok = read_json(LEGACY_TIKTOK_TOKEN, None)
    LEGACY_TIKTOK_TOKEN.unlink(missing_ok=True)
    if not tok or not tok.get("open_id"):
        return
    cfg = load_config()
    aid = account_id("tiktok", tok["open_id"])
    set_token(aid, tok)
    accts = cfg.get("accounts") or []
    if not any(a["id"] == aid for a in accts):
        accts.append({"id": aid, "platform": "tiktok", "name": cfg.get("display_name") or cfg.get("account_handle") or "TikTok",
                      "handle": cfg.get("account_handle") or "", "niches": [], "posts_per_day": None,
                      "mode": "drafts", "privacy": None, "enabled": True})
        cfg["accounts"] = accts
        save_config(cfg)
    for c in Store.all(Store.clips):  # clips sent before accounts existed belong to that login
        if c.get("status") in ("drafted", "posted") and not c.get("account_id"):
            Store.update(Store.clips, c["id"], account_id=aid)


def all_accounts(platform: str | None = None) -> list[dict]:
    with _lock:
        _migrate()
    accts = [dict(a) for a in load_config().get("accounts") or []]
    return [a for a in accts if not platform or a.get("platform") == platform]


def active(platform: str | None = None) -> list[dict]:
    return [a for a in all_accounts(platform) if a.get("enabled", True) and token(a["id"])]


def get(aid: str | None) -> dict | None:
    return next((a for a in all_accounts() if a["id"] == aid), None)


def upsert(acct: dict) -> dict:
    cfg = load_config()
    accts = cfg.get("accounts") or []
    for i, a in enumerate(accts):
        if a["id"] == acct["id"]:
            accts[i] = {**a, **acct}
            break
    else:
        accts.append({"niches": [], "posts_per_day": None, "mode": "drafts", "privacy": None, "enabled": True, **acct})
    cfg["accounts"] = accts
    save_config(cfg)
    return get(acct["id"])


def update(aid: str, patch: dict) -> dict:
    a = get(aid)
    if not a:
        raise KeyError(aid)
    out: dict = {}
    if "handle" in patch:
        out["handle"] = str(patch["handle"] or "").strip().lstrip("@")
    if "niches" in patch:
        out["niches"] = [str(n) for n in (patch["niches"] or [])]
    if "posts_per_day" in patch:
        v = patch["posts_per_day"]
        out["posts_per_day"] = None if v in (None, "", 0) else max(1, min(MAX_PER_DAY, int(v)))
    if "mode" in patch:
        if patch["mode"] not in MODES:
            raise ValueError("mode must be drafts or post")
        out["mode"] = patch["mode"]
    if "privacy" in patch:
        if patch["privacy"] not in PRIVACY + (None, ""):
            raise ValueError("unknown privacy level")
        out["privacy"] = patch["privacy"] or None
    for flag in ("enabled", "allow_comment", "allow_duet", "allow_stitch"):
        if flag in patch:
            out[flag] = bool(patch[flag])
    return upsert({"id": aid, **out})


def remove(aid: str) -> None:
    cfg = load_config()
    cfg["accounts"] = [a for a in cfg.get("accounts") or [] if a["id"] != aid]
    save_config(cfg)
    set_token(aid, None)


# ---------------------------------------------------------------- logins
def token(aid: str) -> dict | None:
    return read_json(TOKENS_FILE, {}).get(aid)


def set_token(aid: str, tok: dict | None) -> None:
    with _lock:
        toks = read_json(TOKENS_FILE, {})
        if tok is None:
            toks.pop(aid, None)
        else:
            toks[aid] = tok
        write_json(TOKENS_FILE, toks)


# ---------------------------------------------------------------- which clip goes to which account
def takes(acct: dict, clip: dict) -> bool:
    return not acct.get("niches") or (clip.get("niche") or "gta6") in acct["niches"]

"""TikTok analytics -> data/metrics.json snapshots + per-clip metrics + campaign earnings.

Backends (config analytics.method = auto | public | display_api):
  public       yt-dlp on https://www.tiktok.com/@handle  (no keys; views/likes/comments/shares)
  display_api  official TikTok API (adds follower count). Used when the TikTok login in
               Connections was granted the optional stats permissions (video.list).
  csv          import of a TikTok Studio export (dashboard upload or CLI).
"""
from __future__ import annotations

import csv
import difflib
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request

from . import accounts, rights, tiktok
from .core import Store, load_config, log, mutate, now_iso, read_json, run_json, write_json, ytdlp_cmd



def tiktok_id_from_url(url: str | None) -> str | None:
    m = re.search(r"/video/(\d{8,})", url or "") or re.fullmatch(r"\s*(\d{15,})\s*", url or "")
    return m.group(1) if m else None


# ---------------------------------------------------------------- backends
def pull_public(handle: str) -> tuple[list[dict], dict]:
    d = run_json(ytdlp_cmd() + ["--flat-playlist", "-J", "--playlist-end", "200",
                                f"https://www.tiktok.com/@{handle}"], timeout=240)
    vids = [{"tiktok_id": str(e["id"]), "views": e.get("view_count"), "likes": e.get("like_count"),
             "comments": e.get("comment_count"), "shares": e.get("repost_count"),
             "created": e.get("timestamp"), "description": e.get("title") or e.get("description") or "",
             "url": f"https://www.tiktok.com/@{handle}/video/{e['id']}"}
            for e in d.get("entries") or [] if e.get("id")]
    return vids, {"followers": d.get("channel_follower_count")}


def _api(method: str, path: str, token: str, body: dict | None = None) -> dict:
    req = urllib.request.Request("https://open.tiktokapis.com/v2/" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def pull_display_api(aid: str) -> tuple[list[dict], dict]:
    token = tiktok.access_token(aid)
    fields = "id,create_time,share_url,video_description,title,duration,view_count,like_count,comment_count,share_count"
    vids, cursor = [], None
    for _ in range(10):
        body = {"max_count": 20, **({"cursor": cursor} if cursor else {})}
        d = _api("POST", f"video/list/?fields={fields}", token, body).get("data", {})
        for v in d.get("videos", []):
            vids.append({"tiktok_id": str(v["id"]), "views": v.get("view_count"), "likes": v.get("like_count"),
                         "comments": v.get("comment_count"), "shares": v.get("share_count"),
                         "created": v.get("create_time"), "url": v.get("share_url"),
                         "description": v.get("video_description") or v.get("title") or ""})
        if not d.get("has_more"):
            break
        cursor = d.get("cursor")
    u = _api("GET", "user/info/?fields=follower_count,likes_count,video_count,display_name", token)
    user = u.get("data", {}).get("user", {})
    return vids, {"followers": user.get("follower_count"), "total_likes": user.get("likes_count")}


def parse_csv(text: str) -> list[dict]:
    """Flexible TikTok Studio export parser: matches columns by keyword."""
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        return []

    def col(*keys):
        for h in rows[0].keys():
            if any(k in (h or "").lower() for k in keys):
                return h
        return None

    c_link, c_views = col("link", "url", "video id", "id"), col("view", "play")
    c_likes, c_comments, c_shares = col("like"), col("comment"), col("share")
    c_title = col("title", "description", "caption")

    def num(v):
        v = (v or "").replace(",", "").strip().upper()
        mult = 1000 if v.endswith("K") else 1_000_000 if v.endswith("M") else 1
        try:
            return int(float(v.rstrip("KM")) * mult)
        except ValueError:
            return None

    out = []
    for r in rows:
        tid = tiktok_id_from_url(r.get(c_link)) if c_link else None
        if not tid:
            continue
        out.append({"tiktok_id": tid, "views": num(r.get(c_views)), "likes": num(r.get(c_likes)),
                    "comments": num(r.get(c_comments)), "shares": num(r.get(c_shares)),
                    "description": r.get(c_title) or "", "url": r.get(c_link)})
    return out


# ---------------------------------------------------------------- record + match
def est_earnings(clip: dict) -> float | None:
    camp = rights.campaign(clip.get("campaign_id"))
    views = (clip.get("metrics") or {}).get("views")
    if not camp or views is None:
        return None
    gross = views / 1000 * float(camp.get("rate_per_1k", 0))
    if camp.get("max_per_clip"):
        gross = min(gross, float(camp["max_per_clip"]))
    fee = float(load_config().get("analytics", {}).get("campaign_fee", 0.10))
    return round(gross * (1 - fee), 2)


def _match_unlinked(vids: list[dict]) -> int:
    """Link TikTok videos to clips the user posted without pasting the URL (caption similarity)."""
    clips = Store.all(Store.clips)
    linked = {c.get("tiktok_id") for c in clips if c.get("tiktok_id")}
    pool = [c for c in clips if not c.get("tiktok_id") and c.get("status") in ("approved", "drafted", "scheduled", "posted")]
    n = 0
    for v in vids:
        if v["tiktok_id"] in linked or not pool:
            continue
        desc = (v.get("description") or "").lower()
        best, best_r = None, 0.0
        for c in pool:
            r = max(difflib.SequenceMatcher(None, desc, (c.get("caption") or "").lower()).ratio(),
                    difflib.SequenceMatcher(None, desc[:80], (c.get("hook") or "").lower()).ratio())
            if r > best_r:
                best, best_r = c, r
        if best and best_r >= 0.6:
            posted = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(v["created"])) if v.get("created") else now_iso()
            Store.update(Store.clips, best["id"], tiktok_id=v["tiktok_id"], tiktok_url=v.get("url"),
                         status="posted", posted_at=best.get("posted_at") or posted)
            pool.remove(best)
            linked.add(v["tiktok_id"])
            n += 1
    return n


def record(vids: list[dict], account: dict, source: str) -> dict:
    ts = now_iso()
    with mutate(Store.metrics, {"account": [], "videos": {}}) as m:
        m["account"].append({"ts": ts, "source": source, "videos": len(vids),
                             "total_views": sum(v.get("views") or 0 for v in vids), **account})
        m["account"] = m["account"][-2000:]
        for v in vids:
            series = m["videos"].setdefault(v["tiktok_id"], [])
            series.append({"ts": ts, **{k: v.get(k) for k in ("views", "likes", "comments", "shares")}})
            m["videos"][v["tiktok_id"]] = series[-500:]
    matched = _match_unlinked(vids)
    by_id = {v["tiktok_id"]: v for v in vids}
    updated = 0
    for c in Store.all(Store.clips):
        v = by_id.get(c.get("tiktok_id") or "")
        if not v:
            continue
        c["metrics"] = {k: v.get(k) for k in ("views", "likes", "comments", "shares")} | {"updated_at": ts}
        Store.update(Store.clips, c["id"], metrics=c["metrics"], est_earnings=est_earnings(c),
                     status="posted" if c.get("status") != "rejected" else c["status"])
        updated += 1
    log(f"analytics[{source}]: {len(vids)} videos, {updated} clips updated, {matched} auto-linked")
    return {"videos": len(vids), "clips_updated": updated, "auto_linked": matched}


def run_metrics() -> dict:
    """Pull stats for every TikTok account (official API where permitted, public profile otherwise)."""
    cfg = load_config()
    method = cfg.get("analytics", {}).get("method", "auto")
    accts = accounts.all_accounts("tiktok") + [
        {"id": None, "name": a.get("name"), "handle": (a.get("platforms") or {}).get("tiktok", {}).get("handle")}
        for a in accounts.all_accounts("uploadpost") if (a.get("platforms") or {}).get("tiktok")]
    uniq, seen = [], set()
    for a in accts:   # the same TikTok may be connected both ways: read it once
        h = (a.get("handle") or "").lower()
        if h and h in seen:
            continue
        seen.add(h)
        uniq.append(a)
    accts = uniq
    accts = accts or [{"id": None, "handle": cfg.get("account_handle")}]
    vids, followers, sources, errors = [], [], set(), []
    for a in accts:
        try:
            if a.get("id") and method in ("auto", "display_api") and "video.list" in tiktok.granted_scopes(a["id"]):
                v, info = pull_display_api(a["id"])
                sources.add("display_api")
            elif a.get("handle"):
                v, info = pull_public(a["handle"])
                sources.add("public")
            else:
                continue
        except Exception as e:  # noqa: BLE001 - one account failing must not hide the others
            errors.append(f"{a.get('name') or a.get('handle')}: {e}")
            log(f"analytics: {errors[-1]}")
            continue
        vids += v
        if info.get("followers") is not None:
            followers.append(info["followers"])
    if not sources:
        raise RuntimeError(errors[0] if errors else "no TikTok handle to read stats from: add the @handle to the account in Connections")
    out = record(vids, {"followers": sum(followers) if followers else None}, "+".join(sorted(sources)))
    return {**out, "errors": errors} if errors else out


def import_csv(text: str) -> dict:
    vids = parse_csv(text)
    if not vids:
        raise RuntimeError("no rows with a TikTok video link/id found in CSV")
    return record(vids, {}, "csv")

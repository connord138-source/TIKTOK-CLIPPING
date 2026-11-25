"""Scout: discover GTA 6 source material and score it by momentum.

Sources
  youtube  – date-filtered search ("uploaded today/this week") over config queries, top
             results enriched with full metadata (upload time, channel, captions, heatmap).
  twitch   – (a) Helix API top GTA VI clips across ALL of Twitch when TWITCH_CLIENT_ID /
             TWITCH_CLIENT_SECRET are set; (b) per-channel top clips for the watchlist.
  url      – anything added by hand (campaign source folders, own footage).
"""
from __future__ import annotations

import json
import math
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from . import rights
from .core import Store, hours_since, load_config, load_sources, log, now_iso, run_json, ytdlp_cmd

YT_FILTERS = {"today": "EgQIAhAB", "week": "EgQIAxAB", "any": "EgIQAQ%3D%3D"}
DEFAULT_RELEVANCE = r"gta\s*(6|vi)\b|gta6|gtavi|grand theft auto (6|vi)|vice city|leonida|\blucia\b"
# Brand safety: TikTok suppresses/bans sexual content hard; never surface it as a source.
DEFAULT_UNSAFE = r"nud(e|ity)|naked|\bnsfw\b|18\+|strip ?club|\bsex|onlyfans|\bporn"


def _relevant(text: str, cfg: dict) -> bool:
    pattern = cfg.get("scout", {}).get("relevance_regex", DEFAULT_RELEVANCE)
    return bool(re.search(pattern, text or "", re.I))


def _ts_iso(ts) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


PREFER = r"funny|moments|highlights?|best of|reacts?|reaction|rage|chase|glitch|bug|easter egg|secret|insane|crazy|fails?|wins?|stunts?|chaos|5 stars?"
AVOID = r"walkthrough|full game|longplay|no commentary|free roam|exploration|\bpart \d+|\b(4k|8k)\b.*(ultra|hdr)|ambien(t|ce)|relaxing|\bintro\b|all cutscenes"


def _unsafe(text: str, cfg: dict) -> bool:
    return bool(re.search(cfg.get("scout", {}).get("unsafe_regex", DEFAULT_UNSAFE), text or "", re.I))


def score_candidate(c: dict) -> float:
    age = c.get("age_hours")
    age = 24.0 if age is None else max(age, 1.0)
    views = c.get("views") or 0
    velocity = views / age
    c["velocity"] = round(velocity, 1)
    s = math.log10(velocity + 1) * 25
    s += 15 if age <= 6 else 8 if age <= 24 else 0
    s += 20 if c.get("relevant") else -30
    s += {"campaign": 25, "permission": 15, "own": 10, "official": 0,
          "unverified": 0, "blocked": -100}.get(c.get("rights"), 0)
    if c.get("unsafe"):
        s -= 200
    dur = c.get("duration") or 0
    if c.get("platform") == "youtube" and dur and dur < 120:
        s -= 15  # short uploads rarely contain a fresh, clippable moment
    if dur > 3 * 3600:
        s -= 40  # day-long streams: slow to process and mostly dead air
    elif dur > 90 * 60:
        s -= 12
    title = c.get("title") or ""
    if re.search(PREFER, title, re.I):
        s += 12  # already-curated or eventful footage clips far better
    if re.search(AVOID, title, re.I):
        s -= 20  # slow, uneventful formats
    return round(s, 1)


def _merge(found: list[dict]) -> tuple[int, int]:
    """Upsert candidates; never clobber workflow status of known ones."""
    existing = {c["id"]: c for c in Store.all(Store.candidates)}
    new = 0
    for c in found:
        old = existing.get(c["id"])
        if old:
            keep = {k: old[k] for k in ("status", "clip_ids", "notes", "rights_override") if k in old}
            if old.get("rights_override"):
                keep["rights"] = old["rights_override"]
            c = {**c, **keep}
        else:
            c.setdefault("status", "new")
            c["discovered_at"] = now_iso()
            new += 1
        c["score"] = score_candidate(c)
        Store.upsert(Store.candidates, c)
    return new, len(found)


# ---------------------------------------------------------------- YouTube
def youtube_meta(url: str) -> dict:
    d = run_json(ytdlp_cmd() + ["-J", "--skip-download", url], timeout=120)
    auto = d.get("automatic_captions") or {}
    subs = d.get("subtitles") or {}
    return {
        "title": d.get("title"),
        "channel": d.get("channel") or d.get("uploader"),
        "channel_id": d.get("channel_id"),
        "channel_followers": d.get("channel_follower_count"),
        "views": d.get("view_count"),
        "likes": d.get("like_count"),
        "duration": d.get("duration"),
        "published_at": _ts_iso(d.get("timestamp")) or (
            datetime.strptime(d["upload_date"], "%Y%m%d").replace(tzinfo=timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ") if d.get("upload_date") else None),
        "live_status": d.get("live_status"),
        "heatmap": [[h["start_time"], h["end_time"], h["value"]] for h in (d.get("heatmap") or [])],
        "has_captions": bool(subs.get("en") or auto.get("en") or auto.get("en-orig")),
        "chapters": [[c["start_time"], c["end_time"], c.get("title")] for c in (d.get("chapters") or [])],
        "thumbnail": d.get("thumbnail"),
    }


def scout_youtube(cfg: dict, extra_queries: list[str] | None = None) -> list[dict]:
    sc = cfg.get("scout", {})
    window = sc.get("youtube_window", "today")
    per_query = sc.get("youtube_results_per_query", 15)
    enrich_top = sc.get("youtube_enrich_top", 12)
    queries = list(dict.fromkeys(sc.get("queries", []) + (extra_queries or [])))
    known = {c["id"]: c for c in Store.all(Store.candidates)}
    flat: dict[str, dict] = {}
    for q in queries:
        url = ("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(q)
               + "&sp=" + YT_FILTERS.get(window, YT_FILTERS["today"]))
        try:
            d = run_json(ytdlp_cmd() + ["--flat-playlist", "-J", "--playlist-end", str(per_query), url])
        except Exception as e:  # noqa: BLE001
            log(f"scout yt '{q}': {e}")
            continue
        for e in d.get("entries") or []:
            if not e.get("id") or e.get("live_status") == "is_live":
                continue
            cid = f"yt:{e['id']}"
            if cid not in flat:
                flat[cid] = {"id": cid, "platform": "youtube", "video_id": e["id"],
                             "url": f"https://www.youtube.com/watch?v={e['id']}",
                             "title": e.get("title"), "views": e.get("view_count") or 0,
                             "duration": e.get("duration"), "query": q,
                             "thumbnail": f"https://i.ytimg.com/vi/{e['id']}/mqdefault.jpg",
                             "relevant": _relevant(e.get("title", ""), cfg)}
    # enrich the most promising unseen ones (full metadata is ~2-4s each)
    ranked = sorted(flat.values(), key=lambda c: (c["relevant"], c["views"]), reverse=True)
    out = []
    enriched = fails = 0
    default_age = {"today": 12, "week": 72}.get(window, 168)
    for c in ranked:
        prior = known.get(c["id"])
        if prior and prior.get("published_at") and (hours_since(prior.get("updated_at")) or 99) < 3:
            continue  # fresh enough; skip the network call
        if fails >= 3 or enriched + fails >= enrich_top:
            # over budget or bot-checked: keep with search-level data (views/title/duration)
            c["meta_error"] = c.get("meta_error") or ("bot-checked" if fails >= 3 else "not enriched")
        else:
            try:
                c.update(youtube_meta(c["url"]))
                enriched += 1
            except Exception as e:  # noqa: BLE001
                fails += 1
                c["meta_error"] = str(e)[:160]
                log(f"scout meta {c['id']}: {str(e)[:120]}")
        if c.get("live_status") in ("is_live", "is_upcoming"):
            continue
        c["age_hours"] = round(hours_since(c.get("published_at")) or default_age, 1)
        c["relevant"] = _relevant(f"{c.get('title')} {c.get('channel')}", cfg)
        c["unsafe"] = _unsafe(c.get("title", ""), cfg)
        c["rights"], c["campaign_id"] = rights.resolve("youtube", c.get("channel_id"), c.get("channel"))
        out.append(c)
    return out


# ---------------------------------------------------------------- Twitch
def _helix_token() -> str | None:
    cid, secret = os.environ.get("TWITCH_CLIENT_ID"), os.environ.get("TWITCH_CLIENT_SECRET")
    if not (cid and secret):
        return None
    body = urllib.parse.urlencode({"client_id": cid, "client_secret": secret,
                                   "grant_type": "client_credentials"}).encode()
    with urllib.request.urlopen("https://id.twitch.tv/oauth2/token", data=body, timeout=20) as r:
        return json.load(r)["access_token"]


def _helix(path: str, token: str) -> dict:
    req = urllib.request.Request("https://api.twitch.tv/helix/" + path, headers={
        "Client-Id": os.environ["TWITCH_CLIENT_ID"], "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _twitch_clip(cfg, *, clip_id, url, title, channel, views, duration, created_at, game_ok, thumbnail=None):
    c = {"id": f"tw:{clip_id}", "platform": "twitch", "url": url, "title": title, "thumbnail": thumbnail,
         "channel": channel, "channel_id": (channel or "").lower(), "views": views,
         "duration": duration, "published_at": created_at,
         "age_hours": round(hours_since(created_at) or 24, 1),
         "relevant": game_ok or _relevant(title, cfg), "unsafe": _unsafe(title, cfg)}
    c["rights"], c["campaign_id"] = rights.resolve("twitch", channel)
    return c


def scout_twitch(cfg: dict) -> list[dict]:
    sc = cfg.get("scout", {})
    out: list[dict] = []
    # (a) category-wide via Helix
    try:
        token = _helix_token()
    except Exception as e:  # noqa: BLE001
        token = None
        log(f"twitch helix auth failed: {e}")
    if token:
        try:
            game = sc.get("twitch_game_name", "Grand Theft Auto VI")
            games = _helix("games?name=" + urllib.parse.quote(game), token).get("data", [])
            if games:
                since = (datetime.now(timezone.utc) - timedelta(hours=sc.get("twitch_window_hours", 24)))
                q = urllib.parse.urlencode({"game_id": games[0]["id"], "first": 50,
                                            "started_at": since.strftime("%Y-%m-%dT%H:%M:%SZ")})
                for cl in _helix("clips?" + q, token).get("data", []):
                    out.append(_twitch_clip(cfg, clip_id=cl["id"], url=cl["url"], title=cl["title"],
                                            channel=cl["broadcaster_name"], views=cl["view_count"],
                                            duration=cl["duration"], created_at=cl["created_at"],
                                            game_ok=True, thumbnail=cl.get("thumbnail_url")))
            else:
                log(f"twitch: game '{game}' not found on Helix")
        except Exception as e:  # noqa: BLE001
            log(f"twitch helix clips: {e}")
    # (b) watchlist channels via yt-dlp
    rng = "24hr" if sc.get("twitch_window_hours", 24) <= 24 else "7d"
    for ch in load_sources().get("channels", []):
        if ch.get("platform") != "twitch" or not ch.get("watch") or ch.get("rights") == "blocked":
            continue
        login = ch.get("login") or ch.get("id")
        try:
            d = run_json(ytdlp_cmd() + ["--flat-playlist", "-J", "--playlist-end", "20",
                                        f"https://www.twitch.tv/{login}/clips?filter=clips&range={rng}"])
        except Exception as e:  # noqa: BLE001
            log(f"scout twitch {login}: {e}")
            continue
        for e in d.get("entries") or []:
            out.append(_twitch_clip(cfg, clip_id=e["id"], url=e["url"], title=e.get("title", ""),
                                    channel=login, views=e.get("view_count") or 0,
                                    duration=e.get("duration"), created_at=_ts_iso(e.get("timestamp")),
                                    game_ok=bool(ch.get("gta_only")), thumbnail=e.get("thumbnail")))
    return out


# ---------------------------------------------------------------- manual
def add_url(url: str, *, rights_level: str = "own", title: str | None = None,
            campaign_id: str | None = None, start: float | None = None, end: float | None = None) -> dict:
    cfg = load_config()
    platform = "youtube" if "youtu" in url else "twitch" if "twitch.tv" in url else "url"
    meta: dict = {}
    if platform == "youtube":
        meta = youtube_meta(url)
    cid = "url:" + re.sub(r"[^A-Za-z0-9]+", "-", url)[-60:]
    if platform == "youtube":
        cid = "yt:" + (re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", url) or [None, cid])[1]
    c = {"id": cid, "platform": platform, "url": url, "title": title or meta.get("title") or url,
         "relevant": True, "rights": rights_level, "rights_override": rights_level,
         "campaign_id": campaign_id, "manual": True, "age_hours": 1, "views": meta.get("views", 0),
         **{k: v for k, v in meta.items() if k not in ("title",)}}
    if start is not None and end is not None:
        c["forced_window"] = [float(start), float(end)]
    c["status"] = "queued"
    _merge([c])
    return Store.get(Store.candidates, cid)


# ---------------------------------------------------------------- entry
def run_scout(extra_queries: list[str] | None = None) -> dict:
    cfg = load_config()
    found = []
    if cfg.get("scout", {}).get("youtube", True):
        found += scout_youtube(cfg, extra_queries)
    if cfg.get("scout", {}).get("twitch", True):
        found += scout_twitch(cfg)
    new, total = _merge(found)
    log(f"scout: {total} candidates seen, {new} new")
    return {"seen": total, "new": new}

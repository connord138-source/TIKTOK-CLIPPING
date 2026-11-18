"""Cadence planner: how many clips to post today, when, and how many to render to keep the
queue full. Phase-based targets (launch surge -> growth -> steady) adjusted by performance.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone

from .core import Store, load_config, parse_iso

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore


def _tz(cfg: dict):
    name = cfg.get("cadence", {}).get("timezone", "America/New_York")
    try:
        return ZoneInfo(name) if ZoneInfo else timezone.utc
    except Exception:  # noqa: BLE001 - missing tzdata on Windows -> UTC
        return timezone.utc


def local_date(iso: str | None, tz) -> str | None:
    dt = parse_iso(iso)
    return dt.astimezone(tz).date().isoformat() if dt else None


def phase_for(cfg: dict, day: str) -> dict:
    for ph in cfg.get("cadence", {}).get("phases", []):
        if not ph.get("until") or day <= ph["until"]:
            return ph
    return {"name": "default", "posts_per_day": 3}


def pick_slots(slots: list[str], n: int) -> list[str]:
    if n <= 0 or not slots:
        return []
    if n >= len(slots):
        return list(slots)
    if n == 1:
        return [slots[len(slots) // 2]]
    return [slots[round(i * (len(slots) - 1) / (n - 1))] for i in range(n)]


def performance(cfg: dict, tz) -> dict:
    """Median views/post, recent vs previous; breakouts; recommendation (+1/0/-1)."""
    now = datetime.now(timezone.utc)
    posted = []
    for c in Store.all(Store.clips):
        dt = parse_iso(c.get("posted_at"))
        views = (c.get("metrics") or {}).get("views")
        if dt and views is not None and now - dt <= timedelta(days=14):
            posted.append((dt, views, c))
    mature = [(dt, v, c) for dt, v, c in posted if now - dt >= timedelta(hours=24)]
    recent = [v for dt, v, _ in mature if now - dt <= timedelta(days=3)]
    prior = [v for dt, v, _ in mature if now - dt > timedelta(days=3)]
    med_all = statistics.median([v for _, v, _ in posted]) if posted else 0
    out = {"posts_14d": len(posted), "median_views_14d": med_all,
           "median_recent_3d": statistics.median(recent) if recent else None,
           "median_prior": statistics.median(prior) if prior else None,
           "breakouts": [], "delta": 0, "reason": "not enough data yet (need posts older than 24h)"}
    for dt, v, c in posted:
        if med_all and v >= 5 * med_all and now - dt <= timedelta(hours=72):
            out["breakouts"].append({"id": c["id"], "views": v, "hook": c.get("hook"),
                                     "channel": c.get("channel")})
    if len(recent) >= 4 and len(prior) >= 6:
        r, p = out["median_recent_3d"], out["median_prior"]
        if p and r >= 1.3 * p:
            out.update(delta=+1, reason=f"recent median {r:.0f} ≥ 1.3× prior {p:.0f}: distribution is expanding — post more")
        elif p and r < 0.6 * p:
            out.update(delta=-1, reason=f"recent median {r:.0f} < 0.6× prior {p:.0f}: likely saturating — post fewer, better")
        else:
            out.update(delta=0, reason=f"recent median {r:.0f} vs prior {p:.0f}: hold cadence")
    if out["breakouts"]:
        out["reason"] += f" · {len(out['breakouts'])} breakout clip(s): prioritize same creator/topic"
    return out


def plan() -> dict:
    cfg = load_config()
    cad = cfg.get("cadence", {})
    tz = _tz(cfg)
    now_local = datetime.now(tz)
    today = now_local.date().isoformat()
    ph = phase_for(cfg, today)
    perf = performance(cfg, tz)
    target = ph.get("posts_per_day", 3)
    adj = cad.get("auto_adjust", {})
    if adj.get("enabled", True) and adj.get("apply", False):
        target += perf["delta"]
    target += cad.get("manual_offset", 0)
    target = max(cad.get("min_posts_per_day", 2), min(cad.get("max_posts_per_day", 6), target))

    clips = Store.all(Store.clips)
    posted_today = [c for c in clips if c.get("status") == "posted" and local_date(c.get("posted_at"), tz) == today]
    ready = sorted([c for c in clips if c.get("status") == "approved"],
                   key=lambda c: c.get("score") or 0, reverse=True)
    review = [c for c in clips if c.get("status") == "rendered"]

    # slot board for today
    slots = pick_slots(cad.get("slots", ["08:00", "12:00", "16:00", "19:00", "22:00"]), target)
    board, queue = [], list(ready)
    filled = len(posted_today)
    for i, hhmm in enumerate(slots):
        h, m = map(int, hhmm.split(":"))
        at = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
        if i < filled:
            board.append({"time": hhmm, "state": "posted", "clip_id": posted_today[i]["id"]})
        elif at < now_local - timedelta(minutes=45):
            board.append({"time": hhmm, "state": "missed", "clip_id": None})
        else:
            clip = queue.pop(0) if queue else None
            board.append({"time": hhmm, "state": "assigned" if clip else "empty",
                          "clip_id": clip["id"] if clip else None, "due": at <= now_local})
    open_slots = sum(1 for b in board if b["state"] in ("assigned", "empty"))

    # production need: fill today's open slots + a buffer, discounting by approval rate
    decided = [c for c in clips if c.get("status") in ("approved", "posted", "rejected")]
    approval = (sum(1 for c in decided if c["status"] != "rejected") / len(decided)) if len(decided) >= 10 else 0.7
    approval = max(approval, 0.3)
    need_ready = open_slots + math.ceil(target * cad.get("buffer_days", 1.0))
    have = len(ready) + len(review) * approval
    renders_needed = max(0, math.ceil((need_ready - have) / approval))

    return {"date": today, "timezone": str(tz), "phase": ph.get("name"), "phase_target": ph.get("posts_per_day"),
            "target": target, "posted_today": len(posted_today), "ready": len(ready), "in_review": len(review),
            "slots": board, "open_slots": open_slots, "approval_rate": round(approval, 2),
            "renders_needed": renders_needed, "performance": perf,
            "next_slot": next((b for b in board if b["state"] in ("assigned", "empty")), None)}


def daily_series(days: int = 30) -> list[dict]:
    """Per local day: posts, views on clips posted that day, est earnings."""
    cfg = load_config()
    tz = _tz(cfg)
    today = datetime.now(tz).date()
    rows = {(today - timedelta(days=i)).isoformat(): {"posts": 0, "views": 0, "earnings": 0.0}
            for i in range(days - 1, -1, -1)}
    for c in Store.all(Store.clips):
        d = local_date(c.get("posted_at"), tz)
        if d in rows:
            rows[d]["posts"] += 1
            rows[d]["views"] += (c.get("metrics") or {}).get("views") or 0
            rows[d]["earnings"] += c.get("est_earnings") or 0
    return [{"date": d, **v} for d, v in rows.items()]

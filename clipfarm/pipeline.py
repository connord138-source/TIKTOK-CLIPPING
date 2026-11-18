"""Agentic workflow orchestration.

Workflows (each runnable from CLI, dashboard, or autopilot):
  scout    discover + score sources; refresh trend queries with Claude every few hours
  produce  pick best rights-cleared candidates -> transcript -> moments -> render -> QC
  metrics  pull TikTok stats, link posts to clips, update earnings
  cycle    scout -> produce -> metrics (what autopilot runs)

Autopilot = a scheduler thread inside the dashboard server that runs these on the cadence in
config.autopilot, only producing as many clips as the planner says the queue needs.
It never posts: clips land in "rendered" for human review (publish_mode: draft_only).
"""
from __future__ import annotations

import shutil
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone

from . import analytics, brain, moments, planner, render, rights, scout, tiktok
from .core import (DATA_DIR, WORK_DIR, Store, _job_ctx, hours_since, load_config, log, mutate,
                   now_iso, read_json)

TRENDS = DATA_DIR / "trends.json"
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


# ---------------------------------------------------------------- produce
def _creator_counts_today() -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    counts: dict = {}
    for c in Store.all(Store.clips):
        if (c.get("created_at") or "").startswith(today):
            counts[c.get("channel")] = counts.get(c.get("channel"), 0) + 1
    return counts


def select_candidates(n: int) -> list[dict]:
    cfg = load_config()
    pc = cfg.get("produce", {})
    min_score = pc.get("min_candidate_score", 40)
    cap = cfg.get("cadence", {}).get("max_per_creator_per_day", 2)
    counts = _creator_counts_today()
    cands = Store.all(Store.candidates)
    queued = [c for c in cands if c.get("status") == "queued"]
    fresh = sorted([c for c in cands if c.get("status") == "new" and c.get("relevant")
                    and (c.get("score") or 0) >= min_score
                    and (hours_since(c.get("published_at")) or 0) <= pc.get("max_source_age_hours", 72)],
                   key=lambda c: c.get("score") or 0, reverse=True)
    picked = list(queued)
    for c in fresh:
        if len(picked) >= n:
            break
        if not rights.auto_render_allowed(c.get("rights", "unverified")):
            if c.get("rights") != "blocked":
                Store.update(Store.candidates, c["id"], status="needs_rights")
            continue
        if counts.get(c.get("channel"), 0) >= cap:
            continue
        counts[c.get("channel")] = counts.get(c.get("channel"), 0) + 1
        picked.append(c)
    return picked[: max(n, len(queued))]


def _compose_caption(pick: dict, cand: dict, cfg: dict) -> tuple[str, list[str]]:
    core = cfg.get("style", {}).get("hashtags_core", ["#gta6", "#gtavi", "#gta", "#gaming", "#fyp"])
    tags = []
    for t in list(pick.get("hashtags") or []) + core:
        t = "#" + t.lstrip("#").replace(" ", "").lower()
        if t != "#" and t not in tags:
            tags.append(t)
    tags = tags[: cfg.get("style", {}).get("max_hashtags", 6)]
    cap = (pick.get("caption") or "").strip()
    cap = " ".join(w for w in cap.split() if not w.startswith("#"))
    tpl = cfg.get("style", {}).get("caption_template", "{caption}\n\n{hashtags}")
    return tpl.format(caption=cap, hashtags=" ".join(tags), channel=cand.get("channel") or ""), tags


def produce_candidate(cand: dict) -> list[str]:
    cfg = load_config()
    Store.update(Store.candidates, cand["id"], status="processing")
    words: list[dict] = []
    if cand.get("platform") == "youtube":
        words = moments.fetch_youtube_words(cand)
        if not cand.get("heatmap") and not cand.get("duration"):
            cand.update(scout.youtube_meta(cand["url"]))
    else:  # whole short source (Twitch clip / file): download first, ASR if available
        src, _ = render.fetch_source(cand, 0, float(cand.get("duration") or 60))
        words = moments.whisper_words(src)
        if not cand.get("duration"):
            cand["duration"] = render.probe(src)["duration"]
    picks = moments.find_moments(cand, words)
    if not picks:
        Store.update(Store.candidates, cand["id"], status="skipped", notes="no clippable moment found")
        return []
    auto = cfg.get("produce", {}).get("auto_approve", {})
    made = []
    for pick in picks:
        clip_id = Store.reserve_clip(status="rendering", candidate_id=cand["id"])
        try:
            out = render.render_clip(cand, pick, clip_id, words)
        except Exception as e:  # noqa: BLE001
            Store.update(Store.clips, clip_id, status="failed", error=str(e)[:400])
            log(f"render {clip_id} failed: {e}")
            continue
        caption, tags = _compose_caption(pick, cand, cfg)
        status = "rendered"
        if (auto.get("enabled") and out["qc"]["ok"] and (pick.get("score") or 0) >= auto.get("min_score", 80)
                and cand.get("rights") in ("campaign", "permission", "own")):
            status = "approved"
        Store.update(Store.clips, clip_id, status=status, platform=cand.get("platform"),
                     source_url=cand["url"], source_title=cand.get("title"), channel=cand.get("channel"),
                     rights=cand.get("rights"), campaign_id=cand.get("campaign_id"),
                     start=pick["start"], end=pick["end"], duration=round(pick["end"] - pick["start"], 1),
                     score=pick.get("score"), hook=pick.get("hook"), caption=caption, hashtags=tags,
                     reason=pick.get("reason"), picked_by=pick.get("source"), **out)
        made.append(clip_id)
        log(f"clip {clip_id} [{status}] {pick.get('hook')!r} ({pick['end'] - pick['start']:.0f}s)")
    Store.update(Store.candidates, cand["id"], status="processed",
                 clip_ids=list(dict.fromkeys((cand.get("clip_ids") or []) + made)))
    return made


def run_produce(max_renders: int | None = None) -> dict:
    cfg = load_config()
    p = planner.plan()
    per_clip = cfg.get("produce", {}).get("max_clips_per_source", 2)
    cap = cfg.get("produce", {}).get("max_renders_per_run", 8)
    want = max_renders if max_renders is not None else min(p["renders_needed"], cap)
    if want <= 0 and not any(c.get("status") == "queued" for c in Store.all(Store.candidates)):
        log(f"produce: queue is full (ready={p['ready']}, review={p['in_review']}) — nothing to do")
        return {"rendered": 0, "reason": "queue full"}
    sources = select_candidates(max(1, -(-want // per_clip)))  # ceil(want / clips-per-source)
    made, failed = [], 0
    for cand in sources:
        if len(made) >= want and cand.get("status") != "queued":
            break
        try:
            made += produce_candidate(cand)
        except Exception as e:  # noqa: BLE001
            failed += 1
            Store.update(Store.candidates, cand["id"], status="failed", notes=str(e)[:300])
            log(f"produce {cand['id']} failed: {e}")
    log(f"produce: {len(made)} clips rendered from {len(sources)} sources ({failed} failed)")
    return {"rendered": len(made), "clips": made, "sources": len(sources), "failed": failed}


# ---------------------------------------------------------------- trends + scout
def refresh_trend_queries(force: bool = False) -> list[str]:
    t = read_json(TRENDS, {})
    hrs = load_config().get("scout", {}).get("trend_refresh_hours", 6)
    if not force and t.get("updated_at") and (hours_since(t["updated_at"]) or 99) < hrs:
        return t.get("queries", [])
    cands = sorted(Store.all(Store.candidates), key=lambda c: c.get("velocity") or 0, reverse=True)
    titles = [c.get("title") or "" for c in cands if (hours_since(c.get("published_at")) or 99) < 48][:40]
    hooks = [c.get("hook") or "" for c in sorted(Store.all(Store.clips),
             key=lambda c: (c.get("metrics") or {}).get("views") or 0, reverse=True)[:15]]
    qs = brain.suggest_queries(titles, hooks) if titles else None
    if qs:
        with mutate(TRENDS, {}) as tr:
            tr.update(queries=qs, updated_at=now_iso())
        log(f"trend queries: {qs}")
        return qs
    return t.get("queries", [])


def run_scout() -> dict:
    res = scout.run_scout(extra_queries=read_json(TRENDS, {}).get("queries", []))
    res["trend_queries"] = refresh_trend_queries()
    return res


def run_cycle() -> dict:
    return {"scout": run_scout(), "produce": run_produce(), "metrics": safe(analytics.run_metrics)}


def safe(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        log(f"{fn.__name__}: {e}")
        return {"error": str(e)}


def cleanup_work(days: float = 3) -> int:
    n = 0
    cutoff = time.time() - days * 86400
    for d in WORK_DIR.glob("*"):
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    return n


# ---------------------------------------------------------------- job runner
WORKFLOWS = {
    "scout": lambda p: run_scout(),
    "produce": lambda p: run_produce(p.get("max_renders")),
    "metrics": lambda p: analytics.run_metrics(),
    "cycle": lambda p: run_cycle(),
    "clip_url": lambda p: _clip_url(p),
    "trends": lambda p: refresh_trend_queries(force=True),
    "rerender": lambda p: rerender(p["clip_id"]),
    "send_draft": lambda p: tiktok.send_clip(p["clip_id"]),
    "send_drafts": lambda p: tiktok.send_ready(p.get("max")),
    "sync_drafts": lambda p: tiktok.sync_drafts(),
}
PARALLEL_OK = {"clip_url", "send_draft"}  # several of these may be queued at once


def rerender(clip_id: str) -> dict:
    """Re-render an existing clip after the user edits hook/bounds in the dashboard."""
    clip = Store.get(Store.clips, clip_id)
    cand = Store.get(Store.candidates, clip["candidate_id"])
    if cand.get("platform") == "youtube":
        words = moments.fetch_youtube_words(cand)
    else:
        src, _ = render.fetch_source(cand, 0, float(cand.get("duration") or 60))
        words = moments.whisper_words(src)
    prev = clip["status"]
    Store.update(Store.clips, clip_id, status="rendering")
    try:
        out = render.render_clip(cand, clip, clip_id, words)
    finally:
        Store.update(Store.clips, clip_id, status=prev)
    Store.update(Store.clips, clip_id, **out)
    return {"clip": clip_id, "qc": out["qc"]}


def _clip_url(p: dict) -> dict:
    cand = scout.add_url(p["url"], rights_level=p.get("rights") or "unverified", title=p.get("title"),
                         campaign_id=p.get("campaign_id"), start=p.get("start"), end=p.get("end"))
    return {"clips": produce_candidate(cand)}


def start_job(kind: str, params: dict | None = None) -> dict:
    if kind not in WORKFLOWS:
        raise ValueError(f"unknown job {kind}")
    with _jobs_lock:
        running = [j for j in _jobs.values() if j["status"] == "running"]
        if any(j["type"] == kind for j in running) and kind not in PARALLEL_OK:
            return next(j for j in running if j["type"] == kind)
        job = {"id": uuid.uuid4().hex[:8], "type": kind, "params": params or {}, "status": "running",
               "started_at": now_iso(), "log": []}
        _jobs[job["id"]] = job

    def body():
        _job_ctx.lines = job["log"]
        try:
            job["result"] = WORKFLOWS[kind](params or {})
            job["status"] = "done"
        except Exception as e:  # noqa: BLE001
            job["status"] = "failed"
            job["error"] = f"{type(e).__name__}: {e}"
            log(traceback.format_exc(limit=3))
        finally:
            job["finished_at"] = now_iso()
            _job_ctx.lines = None
            _persist(job)

    threading.Thread(target=body, daemon=True, name=f"job-{kind}").start()
    return job


def _persist(job: dict) -> None:
    with mutate(Store.jobs, {"history": [], "last": {}}) as j:
        j["history"] = (j.get("history", []) + [{k: v for k, v in job.items() if k != "log"}
                                                | {"log": job["log"][-40:]}])[-100:]
        j.setdefault("last", {})[job["type"]] = job["finished_at"]


def list_jobs() -> list[dict]:
    live = list(_jobs.values())
    hist = read_json(Store.jobs, {}).get("history", [])
    ids = {j["id"] for j in live}
    return sorted(live + [h for h in hist if h["id"] not in ids],
                  key=lambda j: j["started_at"], reverse=True)[:50]


# ---------------------------------------------------------------- autopilot
def _last(kind: str) -> str | None:
    return read_json(Store.jobs, {}).get("last", {}).get(kind)


def autopilot_tick() -> list[str]:
    cfg = load_config()
    ap = cfg.get("autopilot", {})
    if not ap.get("enabled"):
        return []
    started = []
    due = lambda kind, hours: (hours_since(_last(kind)) or 1e9) >= hours  # noqa: E731
    if due("scout", ap.get("scout_every_hours", 2)):
        start_job("scout")
        started.append("scout")
    if due("produce", ap.get("produce_every_hours", 1)) and planner.plan()["renders_needed"] > 0:
        start_job("produce")
        started.append("produce")
    if due("metrics", ap.get("metrics_every_hours", 6)):
        start_job("metrics")
        started.append("metrics")
    if due("cleanup", 24):
        cleanup_work()
        with mutate(Store.jobs, {"history": [], "last": {}}) as j:
            j.setdefault("last", {})["cleanup"] = now_iso()
    return started


_last_draft_sync = [0.0]


def drafts_tick() -> None:
    """Runs whether or not autopilot is on: notice when the user posts a draft from TikTok."""
    if time.time() - _last_draft_sync[0] < 300 or not tiktok.token() or not tiktok._api_drafts():
        return
    _last_draft_sync[0] = time.time()
    res = tiktok.sync_drafts()
    if res["posted"] or res["failed"]:
        log(f"tiktok drafts: {res}")


def reset_stuck() -> None:
    """After a restart nothing is mid-send any more."""
    for c in Store.all(Store.clips):
        if c.get("sending"):
            Store.update(Store.clips, c["id"], sending=False)


def autopilot_loop(stop: threading.Event) -> None:
    while not stop.wait(60):
        try:
            drafts_tick()
            started = autopilot_tick()
            if started:
                log(f"autopilot started: {started}")
        except Exception as e:  # noqa: BLE001
            log(f"autopilot tick error: {e}")

"""Localhost dashboard: stdlib HTTP server + JSON API + static web UI + media streaming.

  python -m clipfarm serve            -> http://127.0.0.1:8787
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import analytics, brain, pipeline, planner, rights, tiktok
from .core import (MEDIA_DIR, ROOT, Store, deep_merge, ensure_dirs, keys_status, load_config,
                   load_sources, log, now_iso, read_json, save_config, save_keys, save_sources)

WEB = Path(__file__).resolve().parent.parent / "web"  # code-relative (data root may differ)
_server = {"port": 8787, "auth_message": None}  # port the dashboard runs on; last TikTok login result

# Explicit types: the Windows registry can map .js/.css to text/plain, which breaks the page.
MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8", ".mp4": "video/mp4", ".jpg": "image/jpeg",
        ".png": "image/png", ".json": "application/json"}

# Settings the UI may change. Everything else is edited in config/*.json by hand or by Claude.
EDITABLE = {"autopilot", "cadence", "produce", "scout", "render", "analytics", "brain", "style", "tiktok"}


def _kpis(clips: list[dict]) -> dict:
    posted = [c for c in clips if c.get("status") == "posted"]
    views = sum((c.get("metrics") or {}).get("views") or 0 for c in posted)
    m = read_json(Store.metrics, {"account": []})
    acct = m["account"][-1] if m["account"] else {}
    followers = next((a.get("followers") for a in reversed(m["account"]) if a.get("followers") is not None), None)
    return {"posted": len(posted), "views": views, "followers": followers,
            "earnings": round(sum(c.get("est_earnings") or 0 for c in posted), 2),
            "avg_views": round(views / len(posted)) if posted else 0,
            "last_metrics_at": acct.get("ts"), "metrics_source": acct.get("source")}


def state() -> dict:
    cfg = load_config()
    clips = Store.all(Store.clips)
    cands = Store.all(Store.candidates)
    by_status: dict = {}
    for c in clips:
        by_status[c.get("status")] = by_status.get(c.get("status"), 0) + 1
    return {
        "handle": cfg.get("account_handle"), "display_name": cfg.get("display_name"),
        "niche": cfg.get("niche"), "publish_mode": cfg.get("publish_mode"),
        "plan": planner.plan(), "kpis": _kpis(clips), "clip_counts": by_status,
        "candidates": {"total": len(cands),
                       "needs_rights": sum(1 for c in cands if c.get("status") == "needs_rights"),
                       "new": sum(1 for c in cands if c.get("status") == "new")},
        "autopilot": cfg.get("autopilot", {}), "brain": brain.available(),
        "tiktok_api": tiktok.status_summary(_server["port"]),
        "trend_queries": read_json(pipeline.TRENDS, {}).get("queries", []),
        "jobs_running": [j["type"] for j in pipeline.list_jobs() if j["status"] == "running"],
        "config": {k: cfg.get(k) for k in EDITABLE},
    }


def analytics_view() -> dict:
    clips = Store.all(Store.clips)
    posted = [c for c in clips if c.get("status") == "posted"]
    by_channel: dict = {}
    for c in posted:
        ch = by_channel.setdefault(c.get("channel") or "?", {"channel": c.get("channel") or "?", "posts": 0, "views": 0})
        ch["posts"] += 1
        ch["views"] += (c.get("metrics") or {}).get("views") or 0
    m = read_json(Store.metrics, {"account": [], "videos": {}})
    table = sorted(({k: c.get(k) for k in ("id", "hook", "channel", "posted_at", "tiktok_url", "score",
                                          "duration", "est_earnings", "campaign_id", "thumb")}
                    | (c.get("metrics") or {}) for c in posted),
                   key=lambda r: r.get("views") or 0, reverse=True)
    return {"daily": planner.daily_series(30), "account": m["account"][-300:],
            "by_channel": sorted(by_channel.values(), key=lambda r: r["views"], reverse=True),
            "clips": table, "performance": planner.plan()["performance"]}


def drafts_view() -> dict:
    """What the /drafts Claude command works from: approved clips in slot order, with the
    absolute file path and the text to prefill; plus clips already sent to TikTok drafts."""
    cfg = load_config()
    clips = {c["id"]: c for c in Store.all(Store.clips)}
    p = planner.plan()
    slot_of = {b["clip_id"]: b["time"] for b in p["slots"] if b.get("clip_id")}
    order = sorted((c for c in clips.values() if c.get("status") == "approved"),
                   key=lambda c: (slot_of.get(c["id"], "99:99"), -(c.get("score") or 0)))
    to_send = []
    for c in order:
        f = (ROOT / c["file"]).resolve() if c.get("file") else None
        to_send.append({"id": c["id"], "slot": slot_of.get(c["id"]), "file": str(f) if f else None,
                        "file_exists": bool(f and f.is_file()),
                        "size_mb": round(f.stat().st_size / 1e6, 1) if f and f.is_file() else None,
                        "duration": c.get("duration"), "title": (c.get("hook") or "")[:150],
                        "description": (c.get("caption") or "")[:4000], "rights": c.get("rights"),
                        "campaign_id": c.get("campaign_id")})
    sent = [{"id": c["id"], "slot": slot_of.get(c["id"]), **(c.get("draft") or {})}
            for c in clips.values() if c.get("status") == "drafted"]
    return {"mode": "UPLOAD_TO_DRAFT", "is_aigc": bool(cfg.get("tiktok", {}).get("ai_generated_label")),
            "open_slots_today": p["open_slots"], "to_send": to_send, "in_tiktok_drafts": sent}


def connections_view() -> dict:
    return {"keys": keys_status(), "tiktok": tiktok.status_summary(_server["port"]),
            "auth_message": _server["auth_message"], "brain": brain.available()}


def clip_action(cid: str, body: dict) -> dict:
    action = body.get("action")
    clip = Store.get(Store.clips, cid)
    if not clip:
        raise KeyError(cid)
    if action == "approve":
        return Store.update(Store.clips, cid, status="approved", approved_at=now_iso())
    if action == "reject":
        return Store.update(Store.clips, cid, status="rejected", reject_reason=body.get("reason"))
    if action == "send_to_drafts":  # one-click: upload to the user's TikTok inbox via TikTok's API
        if clip.get("status") != "approved":
            raise ValueError("approve the clip first")
        if clip.get("sending"):
            return clip
        if not tiktok.status_summary(_server["port"])["can_upload"]:
            raise ValueError("connect TikTok first (Connections tab)")
        updated = Store.update(Store.clips, cid, sending=True, draft_error=None)
        pipeline.start_job("send_draft", {"clip_id": cid})
        return updated
    if action == "drafted":  # recorded by hand or by the Higgsfield /drafts command
        draft = {**(clip.get("draft") or {}), "sent_at": now_iso(),
                 **{k: body[k] for k in ("publish_id", "publish_session_id", "video_url") if body.get(k)}}
        return Store.update(Store.clips, cid, status="drafted", draft=draft)
    if action == "undraft":
        return Store.update(Store.clips, cid, status="approved")
    if action == "unreview":
        return Store.update(Store.clips, cid, status="rendered")
    if action == "posted":
        url = body.get("tiktok_url") or ""
        return Store.update(Store.clips, cid, status="posted", posted_at=body.get("posted_at") or now_iso(),
                            tiktok_url=url or None, tiktok_id=analytics.tiktok_id_from_url(url))
    if action == "edit":
        fields = {k: body[k] for k in ("hook", "caption", "start", "end", "campaign_id") if k in body}
        updated = Store.update(Store.clips, cid, **fields)
        if body.get("rerender"):
            pipeline.start_job("rerender", {"clip_id": cid})
        return updated
    raise ValueError(f"unknown action {action}")


def candidate_action(cid: str, body: dict) -> dict:
    action = body.get("action")
    cand = Store.get(Store.candidates, cid)
    if not cand:
        raise KeyError(cid)
    if body.get("rights"):
        lvl = body["rights"]
        if lvl not in rights.LEVELS:
            raise ValueError("bad rights level")
        Store.update(Store.candidates, cid, rights=lvl, rights_override=lvl,
                     campaign_id=body.get("campaign_id") or cand.get("campaign_id"))
        if body.get("apply_channel") and cand.get("channel"):
            set_channel({"platform": cand["platform"], "id": cand.get("channel_id") or cand["channel"],
                         "name": cand["channel"], "rights": lvl, "campaign_id": body.get("campaign_id")})
            for other in Store.all(Store.candidates):  # propagate to siblings from same channel
                if other.get("channel") == cand["channel"] and other["id"] != cid:
                    Store.update(Store.candidates, other["id"], rights=lvl,
                                 status="new" if other.get("status") == "needs_rights" else other.get("status"))
    if action == "queue":
        return Store.update(Store.candidates, cid, status="queued")
    if action == "skip":
        return Store.update(Store.candidates, cid, status="skipped")
    if action == "reset":
        return Store.update(Store.candidates, cid, status="new")
    return Store.get(Store.candidates, cid)


def set_channel(ch: dict) -> dict:
    src = load_sources()
    key = (ch["platform"], str(ch.get("id") or ch.get("login") or "").lower())
    for existing in src["channels"]:
        if (existing.get("platform"), str(existing.get("id") or existing.get("login") or "").lower()) == key:
            existing.update({k: v for k, v in ch.items() if v is not None})
            break
    else:
        src["channels"].append({k: v for k, v in ch.items() if v is not None})
    save_sources(src)
    return ch


class Handler(BaseHTTPRequestHandler):
    server_version = "clipfarm/1"

    def log_message(self, fmt, *args):  # quieter console
        if not self.path.startswith(("/api/state", "/api/jobs", "/media/", "/static/")):
            log(f"{self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")

    # ---------------------------------------------------------------- helpers
    def _json(self, data, status=200):
        raw = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _redirect(self, to: str):
        self.send_response(302)
        self.send_header("Location", to)
        self.end_headers()

    def _file(self, path: Path):
        if not path.is_file():
            return self._json({"error": "not found"}, 404)
        size = path.stat().st_size
        ctype = MIME.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        rng = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        start, end = 0, size - 1
        if rng and (rng.group(1) or rng.group(2)):
            if rng.group(1):
                start = int(rng.group(1))
                end = int(rng.group(2)) if rng.group(2) else size - 1
            else:
                start = max(0, size - int(rng.group(2)))
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if path.suffix in (".mp4", ".jpg"):
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            try:
                while left > 0:
                    chunk = f.read(min(1 << 16, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _safe_join(self, base: Path, rel: str) -> Path | None:
        p = (base / rel).resolve()
        return p if str(p).startswith(str(base.resolve())) else None

    # ---------------------------------------------------------------- routes
    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path in ("/", "/index.html"):
                return self._file(WEB / "index.html")
            if u.path.startswith("/static/"):
                p = self._safe_join(WEB, u.path[len("/static/"):])
                return self._file(p) if p else self._json({"error": "bad path"}, 400)
            if u.path.startswith("/media/"):
                p = self._safe_join(MEDIA_DIR, u.path[len("/media/"):])
                return self._file(p) if p else self._json({"error": "bad path"}, 400)
            if u.path == "/api/state":
                return self._json(state())
            if u.path == "/api/clips":
                clips = Store.all(Store.clips)
                if q.get("status"):
                    clips = [c for c in clips if c.get("status") in q["status"].split(",")]
                return self._json(sorted(clips, key=lambda c: c["id"], reverse=True))
            if u.path == "/api/candidates":
                c = [x for x in Store.all(Store.candidates) if q.get("unsafe") or not x.get("unsafe")]
                if q.get("status"):
                    c = [x for x in c if x.get("status") in q["status"].split(",")]
                c = sorted(c, key=lambda x: x.get("score") or 0, reverse=True)[: int(q.get("limit", 200))]
                return self._json([{k: v for k, v in x.items() if k != "heatmap"} for x in c])
            if u.path == "/api/sources":
                return self._json(load_sources())
            if u.path == "/api/analytics":
                return self._json(analytics_view())
            if u.path == "/api/jobs":
                return self._json(pipeline.list_jobs())
            if u.path == "/api/connections":
                return self._json(connections_view())
            if u.path == "/auth/tiktok":
                try:
                    return self._redirect(tiktok.authorize_url(_server["port"]))
                except tiktok.TikTokError as e:
                    _server["auth_message"] = {"ok": False, "text": str(e)}
                    return self._redirect("/#connections")
            if u.path.rstrip("/") == "/auth/tiktok/callback":
                try:
                    if q.get("error"):
                        raise tiktok.TikTokError(q["error"], q.get("error_description", ""))
                    tiktok.finish_login(q.get("code", ""), q.get("state", ""), _server["port"])
                    _server["auth_message"] = {"ok": True, "text": "TikTok connected."}
                except tiktok.TikTokError as e:
                    _server["auth_message"] = {"ok": False, "text": str(e)}
                return self._redirect("/#connections")
            return self._json({"error": "not found"}, 404)
        except Exception as e:  # noqa: BLE001
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):  # noqa: N802
        # Custom header blocks cross-site form posts / CSRF against the local server.
        if self.headers.get("X-Clipfarm") != "1":
            return self._json({"error": "missing X-Clipfarm header"}, 403)
        u = urlparse(self.path)
        try:
            raw = self._body()
            if u.path == "/api/import-csv":
                return self._json(analytics.import_csv(raw.decode("utf-8-sig", "replace")))
            body = json.loads(raw or b"{}")
            if m := re.fullmatch(r"/api/clips/(c\d+)", u.path):
                return self._json(clip_action(m.group(1), body))
            if m := re.fullmatch(r"/api/candidates/(.+)", u.path):
                return self._json(candidate_action(m.group(1), body))
            if u.path == "/api/jobs":
                return self._json(pipeline.start_job(body["type"], body.get("params")))
            if u.path == "/api/sources/channel":
                return self._json(set_channel(body))
            if u.path == "/api/sources/campaign":
                src = load_sources()
                src["campaigns"] = [c for c in src["campaigns"] if c.get("id") != body["id"]] + [body]
                save_sources(src)
                return self._json(body)
            if u.path == "/api/connections":
                save_keys(body.get("keys") or {})
                brain._client = None  # pick up a new Claude key on the next call
                return self._json(connections_view())
            if u.path == "/api/tiktok/disconnect":
                tiktok.disconnect()
                _server["auth_message"] = None
                return self._json(connections_view())
            if u.path == "/api/config":
                patch = {k: v for k, v in body.items() if k in EDITABLE}
                cfg = deep_merge(load_config(), patch)
                save_config(cfg)
                return self._json({k: cfg.get(k) for k in EDITABLE})
            return self._json({"error": "not found"}, 404)
        except KeyError as e:
            return self._json({"error": f"not found: {e}"}, 404)
        except (ValueError, json.JSONDecodeError) as e:
            return self._json({"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def serve(host: str = "127.0.0.1", port: int = 8787, autopilot: bool = True) -> None:
    ensure_dirs()
    _server["port"] = port
    pipeline.reset_stuck()
    httpd = ThreadingHTTPServer((host, port), Handler)
    stop = threading.Event()
    if autopilot:
        threading.Thread(target=pipeline.autopilot_loop, args=(stop,), daemon=True, name="autopilot").start()
    ap = "ON" if load_config().get("autopilot", {}).get("enabled") else "OFF (toggle in dashboard)"
    log(f"clipfarm dashboard: http://{host}:{port}   autopilot: {ap}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        httpd.server_close()

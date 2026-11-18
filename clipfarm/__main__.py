"""clipfarm CLI — the same workflows the dashboard/autopilot run, for terminals and Claude agents.

  python -m clipfarm serve [--port 8787] [--host 127.0.0.1] [--no-autopilot]
  python -m clipfarm status                 # plan for today + queue + KPIs (JSON)
  python -m clipfarm scout                  # discover + score GTA 6 sources
  python -m clipfarm produce [--n 4]        # render clips the queue needs (or exactly n)
  python -m clipfarm metrics                # pull TikTok stats, link posts, earnings
  python -m clipfarm cycle                  # scout -> produce -> metrics
  python -m clipfarm clip URL [--start S --end E] [--rights unverified|own|campaign|permission|official]
  python -m clipfarm candidates [--status needs_rights] [--limit 20]
  python -m clipfarm clips [--status rendered]
  python -m clipfarm set-clip c0001 approve|reject|posted [--url TIKTOK_URL] [--reason TEXT]
  python -m clipfarm rerender c0001 [--hook "New hook"] [--start S --end E]
  python -m clipfarm import-csv export.csv
  python -m clipfarm trends                 # force-refresh Claude trend queries
  python -m clipfarm doctor                 # dependency + connectivity check
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str, ensure_ascii=False))


def doctor() -> int:
    from . import brain
    from .core import ytdlp_cmd
    ok = True
    for tool in ("ffmpeg", "ffprobe"):
        found = shutil.which(tool)
        print(f"{'OK ' if found else 'MISSING'} {tool:12} {found or 'install ffmpeg (brew/apt/winget)'}")
        ok &= bool(found)
    try:
        v = subprocess.run(ytdlp_cmd() + ["--version"], capture_output=True, text=True, timeout=30).stdout.strip()
        print(f"OK  yt-dlp       {v}")
    except Exception as e:  # noqa: BLE001
        print(f"MISSING yt-dlp   pip install -r requirements.txt ({e})")
        ok = False
    js = shutil.which("deno") or shutil.which("node")
    print(f"{'OK ' if js else 'WARN'} js runtime   {js or 'install deno (YouTube extraction needs a JS runtime)'}")
    import os
    if not brain.available():
        print("WARN claude brain  pip install anthropic, then set ANTHROPIC_API_KEY (heuristics until then)")
    elif os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        print("OK  claude brain  anthropic SDK + key in env")
    else:
        print("WARN claude brain  SDK installed, no ANTHROPIC_API_KEY in env (fine if you ran `ant auth login`)")
    try:
        import faster_whisper  # noqa: F401
        print("OK  whisper      faster-whisper (captions for Twitch/own footage)")
    except ImportError:
        print("WARN whisper     optional: pip install faster-whisper (Twitch clips render without captions)")
    return 0 if ok else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="clipfarm", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8787)
    s.add_argument("--no-autopilot", action="store_true")
    sub.add_parser("status")
    sub.add_parser("scout")
    pr = sub.add_parser("produce")
    pr.add_argument("--n", type=int, default=None)
    sub.add_parser("metrics")
    sub.add_parser("cycle")
    sub.add_parser("trends")
    sub.add_parser("doctor")
    c = sub.add_parser("clip")
    c.add_argument("url")
    c.add_argument("--start", type=float)
    c.add_argument("--end", type=float)
    c.add_argument("--rights", default="unverified", choices=["unverified", "own", "campaign", "permission", "official"])
    c.add_argument("--campaign")
    ca = sub.add_parser("candidates")
    ca.add_argument("--status")
    ca.add_argument("--limit", type=int, default=20)
    cl = sub.add_parser("clips")
    cl.add_argument("--status")
    sc = sub.add_parser("set-clip")
    sc.add_argument("id")
    sc.add_argument("action", choices=["approve", "reject", "posted", "unreview"])
    sc.add_argument("--url")
    sc.add_argument("--reason")
    rr = sub.add_parser("rerender")
    rr.add_argument("id")
    rr.add_argument("--hook")
    rr.add_argument("--start", type=float)
    rr.add_argument("--end", type=float)
    ic = sub.add_parser("import-csv")
    ic.add_argument("path")
    a = p.parse_args(argv)

    from . import analytics, pipeline, server
    from .core import Store, ensure_dirs
    ensure_dirs()

    if a.cmd == "serve":
        server.serve(a.host, a.port, autopilot=not a.no_autopilot)
    elif a.cmd == "status":
        st = server.state()
        st.pop("config", None)
        _print(st)
    elif a.cmd == "scout":
        _print(pipeline.run_scout())
    elif a.cmd == "produce":
        _print(pipeline.run_produce(a.n))
    elif a.cmd == "metrics":
        _print(analytics.run_metrics())
    elif a.cmd == "cycle":
        _print(pipeline.run_cycle())
    elif a.cmd == "trends":
        _print(pipeline.refresh_trend_queries(force=True))
    elif a.cmd == "doctor":
        return doctor()
    elif a.cmd == "clip":
        _print(pipeline._clip_url({"url": a.url, "start": a.start, "end": a.end,
                                   "rights": a.rights, "campaign_id": a.campaign}))
    elif a.cmd == "candidates":
        rows = Store.all(Store.candidates)
        if a.status:
            rows = [r for r in rows if r.get("status") == a.status]
        rows = sorted(rows, key=lambda r: r.get("score") or 0, reverse=True)[: a.limit]
        _print([{k: r.get(k) for k in ("id", "score", "status", "rights", "channel", "views",
                                       "velocity", "age_hours", "title", "url")} for r in rows])
    elif a.cmd == "clips":
        rows = Store.all(Store.clips)
        if a.status:
            rows = [r for r in rows if r.get("status") == a.status]
        _print([{k: r.get(k) for k in ("id", "status", "score", "hook", "channel", "duration", "file",
                                       "grid", "qc", "metrics")} for r in rows])
    elif a.cmd == "set-clip":
        _print(server.clip_action(a.id, {"action": a.action, "tiktok_url": a.url, "reason": a.reason}))
    elif a.cmd == "rerender":
        fields = {k: v for k, v in (("hook", a.hook), ("start", a.start), ("end", a.end)) if v is not None}
        if fields:
            Store.update(Store.clips, a.id, **fields)
        _print(pipeline.rerender(a.id))
    elif a.cmd == "import-csv":
        with open(a.path, encoding="utf-8-sig") as f:
            _print(analytics.import_csv(f.read()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

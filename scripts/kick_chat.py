#!/usr/bin/env python3
"""Kick VOD helper: list VODs, pull the chat replay, rank chat spikes (moment finder).

Chat spikes (laughs, "clip", KEKW, W spam) point at the moments worth reading in the
transcript. Validated 2026-09-28 on TJR: the Bucktooth Benny bit was the top laugh run.

  kick_chat.py vods tjr                              # recent VODs: index, date, length, views
  kick_chat.py fetch tjr 0 --out work/tjr/chat.json  # chat for VOD #0 (~1 call per 5s of stream;
                                                     #  --minutes 55-70 for a stretch)
  kick_chat.py spikes work/tjr/chat.json --top 20    # 20s windows ranked by volume + laughs

Needs `pip install curl_cffi` (Kick blocks plain clients). The VOD's `source` m3u8 from
`vods` feeds ffmpeg directly: `-ss <start> -i <m3u8> -t <dur> -c copy` (1080p60), and its
160p30 variant is a cheap full-length copy for a whisper scan (see PRODUCE-QUEUE §3).
"""
import argparse
import collections
import datetime as dt
import json
import re
import sys
import time

API = "https://kick.com/api/v2/channels"
LAUGH = re.compile(r"lol|lmao|lmfao|kekw|kekleo|lulw|omegalul|pepelaugh|haha|😂|🤣|💀|😭|"
                   r"crying|dying|clip|holy|insane|goat|\bw\b|wwww|lets go|let's go|banger",
                   re.I)


def session():
    try:
        from curl_cffi import requests
    except ImportError:
        sys.exit("needs curl_cffi: pip install curl_cffi")
    return requests.Session(impersonate="chrome")


def get_vods(s, slug):
    r = s.get(f"{API}/{slug}/videos", timeout=30)
    r.raise_for_status()
    return r.json()


def cmd_vods(args):
    for i, v in enumerate(get_vods(session(), args.slug)[:args.n]):
        print(f"#{i}  {v['start_time']} UTC  {v['duration'] / 60000:6.1f} min  "
              f"{(v.get('views') or 0):>7} views  {v.get('session_title', '')[:60]}")
        print(f"     uuid {v['video']['uuid']}  src {v['source']}")


def cmd_fetch(args):
    s = session()
    v = get_vods(s, args.slug)[args.index]
    t0 = dt.datetime.fromisoformat(v["start_time"].replace(" ", "T") + "+00:00")
    end = t0 + dt.timedelta(milliseconds=v["duration"])
    t = t0
    if args.minutes:  # only part of the stream, e.g. 55-70
        lo, hi = (float(x) for x in args.minutes.split("-"))
        t, end = t0 + dt.timedelta(minutes=lo), min(end, t0 + dt.timedelta(minutes=hi))
    seen, msgs = set(), []
    while t < end:
        data = None
        for attempt in range(4):
            try:
                r = s.get(f"{API}/{v['channel_id']}/messages",
                          params={"start_time": t.strftime("%Y-%m-%dT%H:%M:%S.000Z")},
                          timeout=30)
                data = r.json()
                break
            except Exception:
                time.sleep(2 ** attempt)
        newest = t
        for m in ((data or {}).get("data") or {}).get("messages") or []:
            if m["id"] in seen:
                continue
            seen.add(m["id"])
            ts = dt.datetime.fromisoformat(m["created_at"].replace("Z", "+00:00"))
            msgs.append({"t": round((ts - t0).total_seconds(), 1),
                         "u": m["sender"]["username"], "c": m["content"]})
            newest = max(newest, ts)
        t = max(t + dt.timedelta(seconds=5), newest)  # each call returns ~5s of chat
    msgs.sort(key=lambda m: m["t"])
    json.dump({"vod": v["video"]["uuid"], "start_time": v["start_time"], "messages": msgs},
              open(args.out, "w"))
    print(f"{len(msgs)} messages -> {args.out}")


def cmd_spikes(args):
    msgs = json.load(open(args.chat))["messages"]
    count, laughs = collections.Counter(), collections.Counter()
    for m in msgs:
        b = int(m["t"] // args.window)
        count[b] += 1
        laughs[b] += bool(LAUGH.search(m["c"]))
    ranked = sorted(count, key=lambda b: -(2 * laughs[b] + count[b]))[:args.top]
    for b in sorted(ranked):
        t = b * args.window
        sample = [m["c"][:34] for m in msgs if t <= m["t"] < t + args.window][:6]
        print(f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{int(t % 60):02d}  "
              f"n={count[b]:3d} laughs={laughs[b]:2d} | " + " / ".join(sample))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("vods")
    a.add_argument("slug")
    a.add_argument("-n", type=int, default=10)
    a.set_defaults(func=cmd_vods)
    a = sub.add_parser("fetch")
    a.add_argument("slug")
    a.add_argument("index", type=int, help="VOD index from `vods` (0 = newest)")
    a.add_argument("--out", required=True)
    a.add_argument("--minutes", help="only this stretch of the stream, e.g. 55-70")
    a.set_defaults(func=cmd_fetch)
    a = sub.add_parser("spikes")
    a.add_argument("chat")
    a.add_argument("--top", type=int, default=20)
    a.add_argument("--window", type=float, default=20.0, help="seconds per bin")
    a.set_defaults(func=cmd_spikes)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

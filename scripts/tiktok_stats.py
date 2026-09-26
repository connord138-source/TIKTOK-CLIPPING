#!/usr/bin/env python3
"""TikTok stats for our account from its PUBLIC profile — no login, no API key.

Lists the account's videos with views/likes/comments (yt-dlp, browser-impersonated;
needs `pip install curl_cffi`), reads follower stats from the profile page, links each
video to its ledger entry by the video id in `post_url`, checks every caption against
its campaign's `required_caption_tokens` (e.g. "#ad"), updates the ledger, and writes
work/tiktok/stats.json — board-ready posts/<ledger id> docs + profile numbers — for the
ops-board sync (guard Routine).

Usage:
  tiktok_stats.py              # fetch, update ledger, write work/tiktok/stats.json
  tiktok_stats.py --dry-run    # fetch + print only
  tiktok_stats.py --link v006=7689168883869109518   # attach a video to a ledger entry
"""
import argparse
import json
import math
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger  # noqa: E402  (same-dir script: load/save/now)

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "work" / "tiktok" / "stats.json"
VIDEO_ID = re.compile(r"/video/(\d+)")


def handle() -> str:
    acct = json.loads((REPO / "config" / "account.json").read_text())
    return acct["tiktok"]["handle_confirmed"].lstrip("@")


def ytdlp_json(url: str, flat: bool = False) -> dict:
    cmd = ["yt-dlp", "--impersonate", "chrome", "-J", "--no-warnings"]
    if flat:
        cmd.append("--flat-playlist")
    r = subprocess.run(cmd + [url], capture_output=True, text=True, timeout=240)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-400:])
    return json.loads(r.stdout)


def profile_stats(user: str) -> dict:
    try:
        from curl_cffi import requests
        html = requests.get(f"https://www.tiktok.com/@{user}", impersonate="chrome",
                            timeout=30).text
    except Exception as e:  # stats are a nice-to-have; views are the point
        print(f"profile stats unavailable: {e}", file=sys.stderr)
        return {}
    m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
                  html, re.S)
    if not m:
        return {}
    ui = (json.loads(m.group(1)).get("__DEFAULT_SCOPE__", {})
          .get("webapp.user-detail", {}).get("userInfo", {}))
    s = ui.get("stats") or {}
    return {"followers": s.get("followerCount"), "hearts": s.get("heartCount"),
            "videos": s.get("videoCount"), "following": s.get("followingCount")}


def campaign_terms() -> dict:
    out = {}
    for c in json.loads((REPO / "config" / "campaigns.json").read_text()):
        status = str(c.get("status", ""))
        out[c["id"]] = {
            "rate": float(c.get("rate_per_1k") or 0),
            "min_payout": float(c.get("min_payout_usd") or 0),
            "dead": status.startswith("ENDED") or "DEAD" in status,
            "tokens": c.get("required_caption_tokens") or [],
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--link", action="append", default=[],
                    help="LEDGER_ID=VIDEO_ID — record which TikTok video a clip is")
    a = ap.parse_args()

    user = handle()
    entries = ledger.load()
    by_id = {e["id"]: e for e in entries}
    for pair in a.link:
        lid, _, vid = pair.partition("=")
        by_id[lid]["post_url"] = f"https://www.tiktok.com/@{user}/video/{vid}"

    listing = ytdlp_json(f"https://www.tiktok.com/@{user}", flat=True)
    videos = {v["id"]: v for v in (listing.get("entries") or []) if v and v.get("id")}
    prof = profile_stats(user)
    terms = campaign_terms()
    now_iso, now_ms = ledger.now(), int(datetime.now(timezone.utc).timestamp() * 1000)

    linked, docs = set(), []
    for e in entries:
        m = VIDEO_ID.search(e.get("post_url") or "")
        if not m or m.group(1) not in videos:
            continue
        vid = m.group(1)
        linked.add(vid)
        v = videos[vid]
        caption = v.get("title") or ""
        try:  # the flat listing truncates captions; the video page has the full text
            detail = ytdlp_json(v.get("url") or e["post_url"])
            caption = detail.get("description") or detail.get("title") or caption
            v = {**v, **{k: detail.get(k) for k in
                         ("view_count", "like_count", "comment_count", "repost_count")
                         if detail.get(k) is not None}}
        except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
        views, likes = v.get("view_count") or 0, v.get("like_count") or 0
        comments = v.get("comment_count") or 0
        t = terms.get(e.get("campaign"), {"rate": float(e.get("rate_per_1k") or 0),
                                          "min_payout": 0, "dead": False, "tokens": []})
        missing = [tok for tok in t["tokens"] if tok.lower() not in caption.lower()]
        pays_from = (math.ceil(t["min_payout"] / t["rate"] * 1000)
                     if t["rate"] and t["min_payout"] else 0)
        if t["dead"]:
            state, note = "dead", "pool died — no payout; keeps training the account"
        elif missing:
            state, note = "go", f"CAPTION MISSING {' '.join(missing)} — edit the post, then submit"
        elif views < pays_from:
            state, note = "wait", f"{pays_from - views:,} more views to first payout"
        else:
            state, note = "ok", "earning — past the payout minimum"

        e.update({"views": views, "likes": likes, "comments": comments,
                  "post_url": e.get("post_url"), "caption_live": caption[:300],
                  "caption_missing": missing, "stats_at": now_iso})
        posted = v.get("timestamp")
        docs.append({"doc_id": e["id"], "data": {
            "clip": e.get("board_label") or e.get("title", e["id"])[:60],
            "campaign_id": e.get("campaign"),
            "posted": (datetime.fromtimestamp(posted, timezone.utc).strftime("%m-%d")
                       if posted else str(e.get("posted_at", ""))[5:10]),
            "views": views, "likes": likes, "comments": comments,
            "accruing": round(views / 1000 * t["rate"], 2) if not t["dead"] else 0,
            "state": state, "note": note, "post_url": e.get("post_url"),
            "updated": now_ms}})

    unlinked = [{"video_id": vid, "url": v.get("url"), "views": v.get("view_count"),
                 "caption": (v.get("title") or "")[:90]}
                for vid, v in videos.items() if vid not in linked]
    result = {"generated": now_iso, "handle": user, "profile": prof,
              "posts": docs, "unlinked": unlinked}
    if not a.dry_run:
        ledger.save(entries)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False))

    print(f"@{user}: {prof.get('followers', '?')} followers · {prof.get('hearts', '?')} "
          f"likes · {len(videos)} videos · {len(docs)} linked to ledger")
    for d in docs:
        x = d["data"]
        print(f"  {d['doc_id']:<5} {x['views']:>7,} views {x['likes']:>4} likes "
              f"{x['comments']:>3} cmts  ${x['accruing']:.2f}  {x['state']:<4} {x['note']}")
    for u in unlinked:
        print(f"  UNLINKED {u['video_id']}  {u['views']} views  {u['caption']}  "
              f"-> tiktok_stats.py --link vNNN={u['video_id']}")
    if not a.dry_run:
        print(f"-> {OUT.relative_to(REPO)} (board docs posts/<ledger id>); ledger updated")


if __name__ == "__main__":
    main()

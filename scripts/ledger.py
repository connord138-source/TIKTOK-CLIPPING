#!/usr/bin/env python3
"""Content ledger CLI: track every clip/video from idea to verified payout.

Usage:
  ledger.py add --title "streamer W moment" --campaign whop-xyz --rate-per-1k 1.50 \
      --source-url https://twitch.tv/videos/123 --vod-window 1:10:40-1:11:06
  ledger.py set v001 status=posted tiktok_url=... posted_at=2026-09-23
  ledger.py set v001 verified_views=41000 payout_status=verified
  ledger.py set v001 earnings_usd=61.50 payout_status=paid
  ledger.py list [--status posted] [--campaign whop-xyz]
  ledger.py report
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LEDGER = Path(__file__).resolve().parent.parent / "ledger" / "videos.json"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load() -> list:
    if not LEDGER.exists():
        return []
    return json.loads(LEDGER.read_text())


def save(entries: list) -> None:
    LEDGER.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")


def cast(value: str):
    for caster in (int, float):
        try:
            return caster(value)
        except ValueError:
            pass
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("null", "none"):
        return None
    return value


def find(entries: list, vid: str) -> dict:
    for entry in entries:
        if entry["id"] == vid:
            return entry
    sys.exit(f"error: no ledger entry with id {vid!r}")


def cmd_add(args) -> None:
    entries = load()
    next_num = max((int(e["id"][1:]) for e in entries), default=0) + 1
    entry = {
        "id": f"v{next_num:03d}",
        "idea_id": args.idea_id,
        "title": args.title,
        "status": args.status,
        "credits_spent": 0,
        "created_at": now(),
        "updated_at": now(),
    }
    for key, value in (
        ("campaign", args.campaign),
        ("rate_per_1k", args.rate_per_1k),
        ("source_url", args.source_url),
        ("vod_window", args.vod_window),
        ("clip_file", args.clip_file),
    ):
        if value is not None:
            entry[key] = value
    entries.append(entry)
    save(entries)
    print(f"added {entry['id']}: {entry['title']}")


def cmd_set(args) -> None:
    entries = load()
    entry = find(entries, args.id)
    for pair in args.pairs:
        if "=" not in pair:
            sys.exit(f"error: expected key=value, got {pair!r}")
        key, _, value = pair.partition("=")
        entry[key] = cast(value)
    entry["updated_at"] = now()
    save(entries)
    print(f"updated {entry['id']}: " + ", ".join(args.pairs))


def cmd_list(args) -> None:
    entries = load()
    if args.status:
        entries = [e for e in entries if e.get("status") == args.status]
    if args.campaign:
        entries = [e for e in entries if e.get("campaign") == args.campaign]
    if not entries:
        print("(no entries)")
        return
    print(f"{'id':<6}{'status':<14}{'campaign':<16}{'views':>10}{'$':>8}  title")
    for e in entries:
        print(
            f"{e['id']:<6}{e.get('status', '?'):<14}"
            f"{str(e.get('campaign', '-'))[:15]:<16}"
            f"{e.get('views', '-'):>10}{earnings(e):>8.2f}  "
            f"{e.get('title', '')[:40]}"
        )


def earnings(entry: dict) -> float:
    """Recorded payout, else estimate from verified views x campaign rate."""
    if entry.get("earnings_usd") is not None:
        return float(entry["earnings_usd"])
    views = entry.get("verified_views") or 0
    rate = entry.get("rate_per_1k") or 0
    return views / 1000 * rate


def cmd_report(_args) -> None:
    entries = load()
    if not entries:
        print("Ledger empty — no videos yet.")
        return
    by_status: dict = {}
    for e in entries:
        by_status.setdefault(e.get("status", "?"), []).append(e)
    total_credits = sum(e.get("credits_spent", 0) for e in entries)
    posted = [e for e in entries if e.get("views") is not None]
    total_views = sum(e.get("views", 0) for e in posted)

    print(f"videos: {len(entries)} total")
    for status, group in sorted(by_status.items()):
        print(f"  {status}: {len(group)}")
    print(f"credits spent: {total_credits}")
    if posted:
        print(f"tracked views: {total_views} across {len(posted)} posted videos")
        if total_views:
            print(f"credits per 1k views: {total_credits / total_views * 1000:.1f}")
        top = sorted(posted, key=lambda e: e.get("views", 0), reverse=True)[:3]
        print("top videos:")
        for e in top:
            print(f"  {e['id']} {e.get('views', 0):>8} views  {e.get('title', '')[:40]}")

    by_campaign: dict = {}
    for e in entries:
        if e.get("campaign"):
            by_campaign.setdefault(e["campaign"], []).append(e)
    if by_campaign:
        print("campaigns:")
        total_usd = 0.0
        for name, group in sorted(by_campaign.items()):
            usd = sum(earnings(e) for e in group)
            paid = sum(earnings(e) for e in group
                       if e.get("payout_status") == "paid")
            views = sum(e.get("verified_views") or e.get("views") or 0
                        for e in group)
            total_usd += usd
            print(f"  {name}: {len(group)} clips, {views} views, "
                  f"${usd:.2f} earned (${paid:.2f} paid out)")
        print(f"total earnings: ${total_usd:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="add a new video/clip entry")
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--idea-id", default=None)
    p_add.add_argument("--status", default="planned")
    p_add.add_argument("--campaign", default=None, help="campaign id/name")
    p_add.add_argument("--rate-per-1k", type=float, default=None,
                       help="campaign USD per 1k verified views")
    p_add.add_argument("--source-url", default=None, help="VOD url clipped from")
    p_add.add_argument("--vod-window", default=None, help="e.g. 1:10:40-1:11:06")
    p_add.add_argument("--clip-file", default=None, help="work/<job>/clip-NNN.mp4")
    p_add.set_defaults(func=cmd_add)

    p_set = sub.add_parser("set", help="update fields: set v001 key=value ...")
    p_set.add_argument("id")
    p_set.add_argument("pairs", nargs="+", metavar="key=value")
    p_set.set_defaults(func=cmd_set)

    p_list = sub.add_parser("list", help="list entries")
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--campaign", default=None)
    p_list.set_defaults(func=cmd_list)

    p_report = sub.add_parser("report", help="summary: counts, spend, views, top videos")
    p_report.set_defaults(func=cmd_report)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

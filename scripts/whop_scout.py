#!/usr/bin/env python3
"""Whop Content Rewards (bounties) scout — discovery + rules pull via the Whop API.

Auth: reads the API key from env WHOP_CLIPPING (fallback WHOP_API_KEY). The key is an
environment variable of the Claude cloud environment; env changes apply to sessions
STARTED AFTER saving them. Endpoints mapped 2026-09-23 from the official OpenAPI spec
(docs: dev.whop.com/api-reference/beta/bounties, base https://api.whop.com/api/v1).

Usage:
  whop_scout.py probe                      # auth check: what can this key see?
  whop_scout.py scout [--goal clipping] [--min-reward 100] [--top 15] [--all-goals]
                                           # open bounties -> table + raw dump +
                                           # config/campaigns-proposed.json
  whop_scout.py show BOUNTY_ID             # full rules text for one bounty
  whop_scout.py submissions BOUNTY_ID      # public submissions (what gets accepted)

scout writes PROPOSALS only — joining a campaign stays a user decision; encode joined
campaigns into config/campaigns.json by hand (OPERATIONS §C).
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
API = "https://api.whop.com/api/v1"


def key() -> str:
    k = os.environ.get("WHOP_CLIPPING") or os.environ.get("WHOP_API_KEY")
    if not k:
        sys.exit("whop_scout: no WHOP_CLIPPING in env.\n"
                 "Set it in the cloud environment's Environment variables (gear icon,\n"
                 "same place as Network access) — it reaches sessions STARTED AFTER\n"
                 "saving, so start a fresh session on this repo/branch and rerun.")
    return k.strip()


def get(path: str, params: dict | None = None) -> dict:
    url = API + path + ("?" + urllib.parse.urlencode(
        {k: v for k, v in (params or {}).items() if v is not None}) if params else "")
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key()}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:400]
        sys.exit(f"whop_scout: HTTP {e.code} on {path}\n{body}\n"
                 "(401/403 hints: key type may be wrong for this endpoint — the docs "
                 "distinguish account keys, app keys and user tokens; try `probe`.)")


def money(x) -> str:
    return f"${float(x):,.0f}" if x is not None else "?"


def cmd_probe(_a) -> None:
    data = get("/bounties", {"first": 3})
    rows = data.get("data", [])
    print(f"auth OK — /bounties returned {len(rows)} row(s); "
          f"page_info: {json.dumps(data.get('page_info', {}))[:120]}")
    for b in rows:
        print(f"  {b.get('id')}  [{b.get('status')}] {b.get('title', '')[:60]}")
    if not rows:
        print("empty result: this key likely scopes to your own account's bounties\n"
              "(you have none). Marketplace browsing may need different filters or a\n"
              "user token — try: scout --all-goals, then `show` on a known bounty id\n"
              "from a whop.com campaign URL.")


def normalize(b: dict) -> dict:
    return {
        "bounty_id": b.get("id"),
        "title": b.get("title"),
        "status": b.get("status"),
        "goal": b.get("business_goal_type"),
        "budget": b.get("budget_amount"),
        "reward_total": b.get("gross_reward_amount"),
        "paid_out": b.get("gross_paid_out_amount"),
        "currency": b.get("currency"),
        "spots_remaining": b.get("spots_remaining"),
        "accepted_submissions": b.get("accepted_submissions_count"),
        "per_user_limit": b.get("accepted_submissions_per_user_limit"),
        "min_verified_duration_s": b.get("min_total_verified_duration_seconds"),
        "deliverable_types": b.get("accepted_deliverable_types"),
        "countries": b.get("allowed_country_codes"),
        "poster": (b.get("poster") or {}).get("username"),
        "created_at": b.get("created_at"),
        "url_guess": f"https://whop.com/bounties/{b.get('id')}",
    }


def cmd_scout(a) -> None:
    rows, after = [], None
    while len(rows) < 200:
        data = get("/bounties", {
            "status": "open",
            "business_goal_type": None if a.all_goals else a.goal,
            "order": "gross_reward_amount", "direction": "desc",
            "first": 50, "after": after})
        batch = data.get("data", [])
        rows += batch
        pi = data.get("page_info") or {}
        after = pi.get("end_cursor")
        if not batch or not pi.get("has_next_page"):
            break

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    dump_dir = REPO / "work" / "whop"
    dump_dir.mkdir(parents=True, exist_ok=True)
    (dump_dir / f"bounties-{stamp}.json").write_text(json.dumps(rows, indent=1))

    norm = [normalize(b) for b in rows]
    keep = [n for n in norm
            if (n["reward_total"] or 0) >= a.min_reward
            and (n["spots_remaining"] is None or n["spots_remaining"] != 0)]
    # pool health first (has paid out already), then biggest remaining reward
    keep.sort(key=lambda n: ((n["paid_out"] or 0) > 0,
                             (n["reward_total"] or 0) - (n["paid_out"] or 0)),
              reverse=True)

    (REPO / "config" / "campaigns-proposed.json").write_text(
        json.dumps(keep[:a.top], indent=2) + "\n")

    print(f"{len(rows)} open bounties fetched"
          + ("" if a.all_goals else f" (goal={a.goal})")
          + f"; {len(keep)} pass filters; top {min(a.top, len(keep))} "
            "-> config/campaigns-proposed.json")
    print(f"{'id':<14}{'reward':>9}{'paid':>9}{'spots':>7}  title / poster")
    for n in keep[:a.top]:
        print(f"{str(n['bounty_id'])[:13]:<14}{money(n['reward_total']):>9}"
              f"{money(n['paid_out']):>9}{str(n['spots_remaining']):>7}  "
              f"{(n['title'] or '')[:44]}  @{n['poster']}")
    print("\nnext: whop_scout.py show <id> for full rules; user joins on whop.com; "
          "then encode into config/campaigns.json")


def cmd_show(a) -> None:
    b = get(f"/bounties/{a.bounty_id}")
    b = b.get("data", b)
    n = normalize(b)
    print(json.dumps(n, indent=2))
    print("\n--- description / rules ---\n")
    print(b.get("description") or "(no description)")


def cmd_submissions(a) -> None:
    data = get(f"/bounties/{a.bounty_id}/submissions", {"first": 25})
    for s in data.get("data", []):
        print(json.dumps(s, indent=1)[:400])
        print("---")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("probe", help="auth check").set_defaults(func=cmd_probe)

    ps = sub.add_parser("scout", help="list + filter open bounties")
    ps.add_argument("--goal", default="clipping",
                    help="business_goal_type filter (default clipping)")
    ps.add_argument("--all-goals", action="store_true")
    ps.add_argument("--min-reward", type=float, default=100.0,
                    help="min gross reward pool in campaign currency (default 100)")
    ps.add_argument("--top", type=int, default=15)
    ps.set_defaults(func=cmd_scout)

    pd = sub.add_parser("show", help="one bounty incl. full rules text")
    pd.add_argument("bounty_id")
    pd.set_defaults(func=cmd_show)

    pb = sub.add_parser("submissions", help="public submissions of a bounty")
    pb.add_argument("bounty_id")
    pb.set_defaults(func=cmd_submissions)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Whop Content Rewards (bounties) scout — discovery + rules pull via the Whop API.

Auth: reads the API key from env WHOP_CLIPPING (fallback WHOP_API_KEY). The key is an
environment variable of the Claude cloud environment; env changes apply to sessions
STARTED AFTER saving them. Endpoints mapped 2026-09-23 from the official OpenAPI spec
(docs: dev.whop.com/api-reference/beta/bounties, base https://api.whop.com/api/v1).

KEYLESS discovery also exists (validated in-container 2026-09-23): contentrewards.com
public API `GET /api/campaign/campaigns/discover` (cursor pagination via
`?cursor=<nextCursor>`), detail at `/discover/{id}` — no auth required.

Usage:
  whop_scout.py discover [--min-remaining 2000] [--top 20]   # NO KEY NEEDED
                                           # contentrewards public API -> table +
                                           # raw dump + config/campaigns-discovered.json
  whop_scout.py detail CAMPAIGN_ID         # keyless: one campaign incl. rules/links
  whop_scout.py probe                      # Whop API key auth check
  whop_scout.py scout [--goal clipping] [--min-reward 100] [--top 15] [--all-goals]
                                           # authed bounties -> campaigns-discovered.json
  whop_scout.py show BOUNTY_ID             # authed: full rules text for one bounty
  whop_scout.py submissions BOUNTY_ID      # authed: public submissions of a bounty

File contract: auto-generated lists -> config/campaigns-discovered.json; the curated
shortlist a session prepares -> config/campaigns-proposed.json; JOINED campaigns
(user decision) -> config/campaigns.json (OPERATIONS §C).
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


CR_API = "https://contentrewards.com/api/campaign/campaigns/discover"


def cr_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/128"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def cr_normalize(c: dict) -> dict:
    m = c.get("metrics") or {}
    budget = (c.get("budgetCents") or 0) / 100
    spent = (m.get("budgetSpentCents") or 0) / 100
    return {
        "campaign_id": c.get("id"),
        "name": c.get("name"),
        "org": c.get("organizationName"),
        "org_verified": c.get("organizationVerified"),
        "categories": c.get("categories"),
        "payout_type": c.get("payoutType"),
        "cpm_min_usd_per_1k": (c.get("cpmMinRateCents") or 0) / 100,
        "cpm_max_usd_per_1k": (c.get("cpmMaxRateCents") or 0) / 100,
        "budget_usd": budget,
        "spent_usd": spent,
        "remaining_usd": round(budget - spent, 2),
        "approved_submissions": m.get("approvedSubmissionCount"),
        "listed_at": c.get("listedAt"),
    }


def cmd_discover(a) -> None:
    rows, cursor, pages = [], None, 0
    while pages < 15:
        url = CR_API + (f"?cursor={urllib.parse.quote(cursor)}" if cursor else "")
        d = cr_get(url)
        batch = d.get("data") or []
        rows += batch
        pages += 1
        cursor = (d.get("pagination") or {}).get("nextCursor")
        if not batch or not cursor:
            break

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    dump_dir = REPO / "work" / "whop"
    dump_dir.mkdir(parents=True, exist_ok=True)
    (dump_dir / f"cr-discover-{stamp}.json").write_text(json.dumps(rows, indent=1))

    norm = [cr_normalize(c) for c in rows]
    keep = [n for n in norm if n["remaining_usd"] >= a.min_remaining]
    keep.sort(key=lambda n: (n["spent_usd"] > 0, n["cpm_max_usd_per_1k"],
                             n["remaining_usd"]), reverse=True)
    (REPO / "config" / "campaigns-discovered.json").write_text(
        json.dumps(keep[:a.top], indent=2) + "\n")

    print(f"{len(rows)} campaigns fetched (keyless), {len(keep)} with >= "
          f"${a.min_remaining:,.0f} remaining; top {min(a.top, len(keep))} "
          "-> config/campaigns-discovered.json")
    print(f"{'cpm':>6}{'remain':>10}{'spent':>10}  name / org")
    for n in keep[:a.top]:
        print(f"{n['cpm_max_usd_per_1k']:>6.2f}{money(n['remaining_usd']):>10}"
              f"{money(n['spent_usd']):>10}  {(n['name'] or '')[:46]}  "
              f"[{n['org']}{'✓' if n['org_verified'] else ''}]")
    print("\nnote: category/platform/rules need `detail <id>` — the list payload "
          "doesn't carry them all.")


def cmd_detail(a) -> None:
    d = cr_get(f"{CR_API}/{a.campaign_id}")
    c = d.get("data", d)
    print(json.dumps(cr_normalize(c), indent=2))
    desc = c.get("description")
    if desc:
        print("\n--- description / rules ---\n")
        print(desc[:6000])
    extras = {k: v for k, v in c.items()
              if k not in ("description", "metrics") and isinstance(v, (str, int, float, bool, list))
              and k not in cr_normalize(c)}
    print("\n--- other fields ---")
    print(json.dumps(extras, indent=1)[:3000])


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

    (REPO / "config" / "campaigns-discovered.json").write_text(
        json.dumps(keep[:a.top], indent=2) + "\n")

    print(f"{len(rows)} open bounties fetched"
          + ("" if a.all_goals else f" (goal={a.goal})")
          + f"; {len(keep)} pass filters; top {min(a.top, len(keep))} "
            "-> config/campaigns-discovered.json")
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

    pdis = sub.add_parser("discover", help="KEYLESS: contentrewards public API")
    pdis.add_argument("--min-remaining", type=float, default=2000.0,
                      help="min remaining budget USD (default 2000)")
    pdis.add_argument("--top", type=int, default=20)
    pdis.set_defaults(func=cmd_discover)

    pdet = sub.add_parser("detail", help="KEYLESS: one campaign incl. rules")
    pdet.add_argument("campaign_id")
    pdet.set_defaults(func=cmd_detail)

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

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
  whop_scout.py board-feed [--min-rate 0.75] [--min-remaining 1500] [--top 10]
                                           # keyless: gaming/streamer campaigns ranked by
                                           # money -> work/whop/board-feed.json (board docs)
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
import math
import os
import re
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


def cr_fetch_all(max_pages: int = 15) -> list:
    rows, cursor, pages = [], None, 0
    while pages < max_pages:
        url = CR_API + (f"?cursor={urllib.parse.quote(cursor)}" if cursor else "")
        d = cr_get(url)
        batch = d.get("data") or []
        rows += batch
        pages += 1
        cursor = (d.get("pagination") or {}).get("nextCursor")
        if not batch or not cursor:
            break
    return rows


def cmd_discover(a) -> None:
    rows = cr_fetch_all()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    dump_dir = REPO / "work" / "whop"
    dump_dir.mkdir(parents=True, exist_ok=True)
    (dump_dir / f"cr-discover-{stamp}.json").write_text(json.dumps(rows, indent=1))

    norm = [cr_normalize(c) for c in rows]
    keep = [n for n in norm if n["remaining_usd"] >= a.min_remaining]
    keep.sort(key=lambda n: (n["spent_usd"] > 0, n["cpm_max_usd_per_1k"],
                             n["remaining_usd"]), reverse=True)
    if keep:
        (REPO / "config" / "campaigns-discovered.json").write_text(
            json.dumps(keep[:a.top], indent=2) + "\n")
    else:
        print("0 rows after filters — keeping the existing "
              "config/campaigns-discovered.json snapshot untouched")

    print(f"{len(rows)} campaigns fetched (keyless), {len(keep)} with >= "
          f"${a.min_remaining:,.0f} remaining; top {min(a.top, len(keep))} "
          "-> config/campaigns-discovered.json")
    print(f"{'cpm':>6}{'remain':>10}{'spent':>10}  name / org")
    for n in keep[:a.top]:
        print(f"{n['cpm_max_usd_per_1k']:>6.2f}{money(n['remaining_usd']):>10}"
              f"{money(n['spent_usd']):>10}  {(n['name'] or '')[:46]}  "
              f"[{n['org']}{'✓' if n['org_verified'] else ''}]")
    print("\nnote: the list payload carries categories/platforms/payouts/"
          "requiresApplication/referenceMaterials — `board-feed` ranks our niche by money.")
    wl = REPO / "config" / "streamer-watchlist.json"
    if wl.exists():
        targets = json.loads(wl.read_text()).get("tier1_brand_targets", [])
        seen = []
        for c in rows:
            text = f"{c.get('name','')} {c.get('organizationName','')}".lower()
            for t in targets:
                if all(part in text for part in t.split()):
                    seen.append((t, c.get("name"), c.get("id")))
        if seen:
            print("\n🎯 WATCHLIST HITS (tier-1 brand streamers):")
            for t, name, cid in seen:
                print(f"  [{t}] {name[:60]}  id={cid}")
        else:
            print("watchlist: no tier-1 streamer programs in public feed this scan")


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

    if keep:
        (REPO / "config" / "campaigns-discovered.json").write_text(
            json.dumps(keep[:a.top], indent=2) + "\n")
    else:
        print("0 rows after filters — keeping the existing "
              "config/campaigns-discovered.json snapshot untouched "
              "(company-scoped keys see only your own bounties)")

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



def cmd_pools(_a) -> None:
    """Live pool check for every campaign in campaigns.json + campaigns-proposed.json."""
    ids = []
    for fname in ("campaigns.json", "campaigns-proposed.json"):
        f = REPO / "config" / fname
        if f.exists():
            for c in json.loads(f.read_text()):
                cid = c.get("cr_campaign_id")
                if cid and len(cid) == 36:
                    ids.append((c.get("id"), cid))
    print(f"{'campaign':<28}{'remaining':>12}{'of budget':>12}  flag")
    for name, cid in ids:
        try:
            d = cr_get(f"{CR_API}/{cid}")
            c = d.get("data", d)
            n = cr_normalize(c)
            rem, bud = n["remaining_usd"], n["budget_usd"]
            flag = ("DEAD" if rem <= 50 else "LOW <$2k" if rem < 2000 else "ok")
            print(f"{name:<28}{'$' + format(rem, ',.0f'):>12}"
                  f"{'$' + format(bud, ',.0f'):>12}  {flag}")
        except Exception as e:
            print(f"{name:<28}{'?':>12}{'?':>12}  lookup failed: {e}")


NICHE_KW = re.compile(
    r"\b(stream(er|ers|ing)?|livestream(er|ers|s)?|twitch|kick(\.com| stream)|esports?|"
    r"gaming|gamer|valorant|fortnite|call of duty|warzone|minecraft|roblox|gta|"
    r"league of legends|apex legends|overwatch|rocket league|speedrun)\b", re.I)
STRONG_KW = re.compile(
    r"\b(twitch|kick(\.com| stream)|esports?|gaming|gamer|streamers?|valorant|fortnite|"
    r"call of duty|warzone|minecraft|roblox|gta|league of legends|apex legends|"
    r"overwatch|rocket league|speedrun)\b", re.I)
SKIP_CATS = {"music", "casino", "gambling", "adult", "dating", "politics"}
SKIP_FORMAT = re.compile(
    r"\b(ugc|slideshows?|talking[- ]head|sound campaign|audio[- ]clipping)\b", re.I)
GEO_LOCK = re.compile(
    r"^\s*[\[(](?!US\b|USA\b|EN\b|ENG\b|English\b)[^\])]{2,20}[\])]", re.I)


def money_metrics(c: dict) -> dict:
    """What a campaign is worth to a small TikTok account: TikTok rate, the views a
    post needs before it pays anything, and how long the pool lasts at its burn."""
    tt = next((p for p in (c.get("payouts") or []) if p.get("platform") == "tiktok"), {})
    rate = (tt.get("rateCents") or c.get("cpmMaxRateCents") or 0) / 100
    min_pay = (tt.get("minPayoutCents") or 0) / 100
    max_pay = (tt.get("maxPayoutCents") or 0) / 100 or None
    n = cr_normalize(c)
    try:
        listed = datetime.fromisoformat(
            (c.get("listedAt") or c.get("createdAt")).replace("Z", "+00:00"))
        age_d = max(0.5, (datetime.now(timezone.utc) - listed).total_seconds() / 86400)
    except (AttributeError, ValueError):
        age_d = 7.0
    burn = n["spent_usd"] / age_d if n["spent_usd"] > 0 else 0.0
    runway = round(n["remaining_usd"] / burn, 1) if burn > 0 else 99.0
    pays_from = math.ceil(min_pay / rate * 1000) if rate > 0 and min_pay > 0 else 0
    threshold = (1.0 if pays_from <= 1000 else 0.8 if pays_from <= 2000
                 else 0.55 if pays_from <= 5000 else 0.3)
    return {"rate": rate, "per10k": round(rate * 10, 2), "min_payout": min_pay,
            "max_payout": max_pay, "pays_from_views": pays_from,
            "burn_per_day": round(burn), "runway_days": runway,
            "score": round(rate * 10 * threshold * min(1.0, runway / 3.0), 2)}


def cmd_board_feed(a) -> None:
    """Niche-filtered, money-ranked NEW campaigns as ops-board docs (campaigns/<doc_id>)."""
    rows = cr_fetch_all()
    tracked = set()
    for fname in ("campaigns.json", "campaigns-proposed.json"):
        f = REPO / "config" / fname
        if f.exists():
            tracked |= {c.get("cr_campaign_id") for c in json.loads(f.read_text())}
    wl = REPO / "config" / "streamer-watchlist.json"
    targets = json.loads(wl.read_text()).get("tier1_brand_targets", []) if wl.exists() else []
    seen_f = REPO / "config" / "discovered-seen.json"
    seen = json.loads(seen_f.read_text()) if seen_f.exists() else {}
    now = datetime.now(timezone.utc)
    today, now_ms = now.strftime("%Y-%m-%d"), int(now.timestamp() * 1000)

    docs, skipped = [], []
    for c in rows:
        cid = c.get("id") or ""
        if len(cid) != 36 or cid in tracked:
            continue
        name = c.get("name") or ""
        cats = {x.get("id") for x in (c.get("categories") or [])}
        text = f"{name} {c.get('organizationName', '')} {(c.get('description') or '')[:800]}"
        wl_hits = [t for t in targets if all(p in text.lower() for p in t.split())]
        desc = (c.get("description") or "")[:800]
        if not ("gaming" in cats or wl_hits or NICHE_KW.search(name)
                or STRONG_KW.search(desc)):
            continue
        n, m = cr_normalize(c), money_metrics(c)
        why = []
        if cats & SKIP_CATS and not wl_hits:
            why.append("off-niche category")
        if SKIP_FORMAT.search(name):
            why.append("format we don't make")
        if GEO_LOCK.search(name):
            why.append("geo/language-locked")
        if "tiktok" not in (c.get("platforms") or []):
            why.append("no TikTok")
        if c.get("private") or c.get("status") != "active":
            why.append("not open")
        if m["rate"] < a.min_rate:
            why.append(f"${m['rate']:.2f}/1k")
        if n["remaining_usd"] < a.min_remaining:
            why.append(f"pool ${n['remaining_usd']:,.0f}")
        if m["runway_days"] < 1:
            why.append("drains within a day")
        if why:
            skipped.append((name, "; ".join(why)))
            continue

        gated = bool(c.get("requiresApplication"))
        plats = "+".join({"tiktok": "TT", "instagram": "IG", "youtube": "YT"}.get(p, p)
                         for p in (c.get("platforms") or []))
        rate_s = f"${m['rate']:.2f}/1k · {plats}"
        if m["pays_from_views"]:
            rate_s += f" · pays from {m['pays_from_views'] / 1000:g}k views"
        if m["max_payout"]:
            rate_s += f" · max ${m['max_payout']:,.0f}/post"
        runway = ("fresh pool, barely touched" if n["spent_usd"] < 0.1 * n["budget_usd"]
                  else "60+ days of pool at current burn" if m["runway_days"] >= 60
                  else f"~{m['runway_days']:.0f} days of pool at current burn")
        chips = [f"${m['per10k']:g} per 10k views"]
        if gated:
            chips.append("application required")
        chips += [f"watchlist: {t}" for t in wl_hits]
        chips += sorted(cats - {"gaming"})[:2]
        docs.append({"doc_id": "cr-" + cid[:8], "data": {
            "name": name.strip(), "org": c.get("organizationName"), "rate": rate_s,
            "rem": round(n["remaining_usd"]), "bud": round(n["budget_usd"]),
            "flag": "hold" if gated else "ok", "can_queue": not gated,
            "url": f"https://contentrewards.com/discover/{cid}",
            "note": (f"found {seen.get(cid, today)} · {runway}"
                     + (" · apply on the campaign page first" if gated else "")),
            "rules": chips, "discovered": True, "first_seen": seen.get(cid, today),
            "cr_campaign_id": cid, "money": m, "updated": now_ms}})

    docs.sort(key=lambda d: d["data"]["money"]["score"], reverse=True)
    docs = docs[:a.top]
    for d in docs:
        seen.setdefault(d["data"]["cr_campaign_id"], today)
    seen_f.write_text(json.dumps(seen, indent=1, sort_keys=True) + "\n")
    out = REPO / "work" / "whop" / "board-feed.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"generated": now.isoformat(), "docs": docs,
                               "skipped": skipped}, indent=1))

    print(f"{len(rows)} campaigns scanned; {len(docs)} niche + money-qualified "
          f"-> {out.relative_to(REPO)} (board docs campaigns/<doc_id>)")
    print(f"{'score':>6}{'$/10k':>7}{'pays@':>7}{'runway':>8}{'left':>9}  name")
    for d in docs:
        x, m = d["data"], d["data"]["money"]
        print(f"{m['score']:>6.1f}{m['per10k']:>7.1f}{m['pays_from_views']:>7}"
              f"{m['runway_days']:>7.0f}d{'$' + format(x['rem'], ','):>9}  "
              f"{x['name'][:44]}{'  [APPLY]' if not x['can_queue'] else ''}  {d['doc_id']}")
    if skipped:
        print(f"\nniche-matched but skipped ({len(skipped)}):")
        for name, why in skipped[:12]:
            print(f"  - {name[:48]}: {why}")


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

    sub.add_parser("pools", help="KEYLESS: live pool status of tracked campaigns"
                   ).set_defaults(func=cmd_pools)

    pbf = sub.add_parser("board-feed",
                         help="KEYLESS: niche-filtered, money-ranked new campaigns "
                              "as ops-board docs")
    pbf.add_argument("--min-rate", type=float, default=0.75,
                     help="min TikTok $/1k (default 0.75)")
    pbf.add_argument("--min-remaining", type=float, default=1500.0,
                     help="min remaining pool USD (default 1500)")
    pbf.add_argument("--top", type=int, default=10)
    pbf.set_defaults(func=cmd_board_feed)

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

# Setup — one-time checklist

## Account status snapshot (2026-09-22)
- Higgsfield: **Plus plan, 461 credits**, one private workspace (selected)
- TikTok: **no account connected** (`tiktok_accounts` → empty)
- Shorts Studio: available, 8+ style presets browsed (Bold Urban, Claymation, …), custom presets possible
- Key models confirmed: `seedance_2_5` (4–30s, native audio, 9:16), `flux_3_video`
  (5–20s, synced audio), `gemini_omni_flash_1_1` (3–10s, up to 4K), `minimax_h3_max` (fast)

## Your part (the 1%)

1. **Confirm the niche** — recommended: POV History (see STRATEGY.md §2). Say "go" to
   accept, or name a different direction and Claude reseeds the backlog for it.
2. **Create the TikTok account** (fresh account, business-of-one hygiene):
   - Handle ideas: `@youwerethere.pov`, `@firstperson.history`, `@wakeupin1347`,
     `@povtimemachine`, `@thedaybefore.pov`
   - Bio pattern: "Daily first-person history. You're there. 🕰️ Part 2 every day."
   - Optional but recommended: 2–3 days of scrolling history/POV content on the new
     account before first post, so the FYP graph seeds toward the right audience.
3. **Connect TikTok to Higgsfield:** ask Claude to run `tiktok_connect` — it returns an
   OAuth link only you can click. After connecting, Claude records the `connector_id`
   in `config/account.json`.
4. **Credits runway:** 461 credits ≈ one launch batch (2–3 videos) + a follow-up. For
   2/day cadence expect to top up — decide budget after batch 1 calibrates real costs
   (cost table in OPERATIONS.md). Claude will show plans/checkout links only when you ask.
5. **Say "go".** Claude runs Production Session #1: scripts + generates the top 2–3
   backlog ideas within budget caps, quality-gates them, and stages TikTok drafts (or
   hands you finished videos if TikTok isn't connected yet).

## Later, when justified by data
- **Daily Routine:** Claude can schedule itself to run a production session every day
  and a metrics session weekly — opt-in, since it spends credits unattended.
- **Dashboard frontend:** ledger `report` is enough pre-launch; once there are >20 posts
  of metrics, build the dashboard (published artifact or a small Worker).
- **Cross-posting:** YouTube Shorts + Instagram Reels reuse of the same files.
- **Second revenue stream:** clipping bounties (Whop-style) if you join a program —
  separate content stream with its own rules; Claude sets it up alongside.

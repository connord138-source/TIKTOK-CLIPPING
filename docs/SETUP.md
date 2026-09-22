# Setup — one-time checklist (clipping era)

## Status snapshot (2026-09-22, post network flip)
- Environment network: **OPEN** (Full) — verified; `clipper.py doctor` re-checks each session
- Editing pipeline: **built + validated E2E** (`scripts/clipper.py`, see CAPABILITY-NOTES)
- Higgsfield: Plus plan, ~461 credits (unused by clipping; garnish only)
- TikTok: account not created yet; nothing connected
- Campaigns: none joined yet → `config/campaigns.json` empty

## Your part (the 1%) — in order

1. **Whop side** 👤
   - Create/sign in to a Whop account (whop.com → Content Rewards); browse campaigns.
   - Pick 1–3 campaigns (gaming/streamer culture preferred — see STRATEGY §3 for
     what makes a good one). Paste each campaign's brief, rate, rules, and source
     links into a session; Claude encodes them in `config/campaigns.json`.
2. **TikTok account** 👤
   - Create **@chat.clip.that** ("CHAT, CLIP THAT 🎬"). Fresh account, real phone/email.
   - Bio pattern: "the moments chat begged us to clip 🎬 daily".
   - Scroll gaming/streamer content 2–3 days before first post so the FYP graph seeds
     toward the right audience (optional but cheap).
3. **First clips** — say "run a clip session" once ≥1 campaign is in
   `campaigns.json`. Claude ingests, cuts, QCs, and sends you finished files +
   post text. You post from the app (campaigns require account-holder posting
   anyway). Turn on the AI-generated label only when a clip actually contains an
   added AI element — Claude flags which.
4. **Metrics loop** 👤 — 24–48h after posts: relay view counts + campaign dashboard
   numbers (screenshots fine). Claude ledgers them and tunes the campaign mix.

## Optional / later
- **`tiktok_connect`** (OAuth link only you can click) — enables staged drafts via
  `tiktok_prepare_publish` instead of file-send. Not required for the core loop.
- **Payout details on Whop** 👤 — needed before first withdrawal; note thresholds.
- **Cross-posting** YT Shorts / IG Reels where campaign rules allow.
- **Daily Routine** (Claude wakes itself for a clip session) — opt-in later; runs
  without credits but still your call.
- **YouTube-source campaigns:** YouTube media is bot-checked from this container;
  if a campaign needs it, export browser cookies for yt-dlp (Claude explains when
  relevant) or use campaign-provided files.

# CLAUDE.md — Operator Brief

This repo is the brain and state store for a TikTok short-form content business
operated by Claude sessions using the Higgsfield MCP tools. The repo holds
strategy, config, the idea backlog, and the content ledger; Claude sessions do
the production work (generate → review → prepare draft → log → push).

## Source of truth
- `config/account.json` — operating config (niche, cadence, budget caps, publish mode)
- `content/backlog.json` — scored idea backlog
- `ledger/videos.json` — every video's lifecycle + real credit costs + metrics (via `scripts/ledger.py`)
- `docs/OPERATIONS.md` — the session runbook. Follow it for any production/metrics session.

## Hard rules (do not violate without the user changing config or saying so in-session)
1. **Never direct-publish to TikTok.** Prepare drafts only (`tiktok_prepare_publish`); the
   user taps post from the TikTok app. `publish_mode` in config governs this.
2. **Budget guardrails before generating:** check `mcp__HIGGSFIELD__balance`. Stop
   generating if balance would drop below `budget.balance_floor_credits`; never spend more
   than `budget.session_cap_credits` in one session; max 1 regeneration per weak concept.
3. **Log every credit.** Each generation's actual cost goes into the ledger entry
   (`credits_spent`). Update the cost table in `docs/OPERATIONS.md` when real numbers land.
4. **Content safety for account survival:** no real-person likenesses, no copyrighted
   characters, original scripts only, AI-generated label ON for every post. See
   STRATEGY.md → Risks.
5. **End every session with commit + push** to the working branch so state survives the
   ephemeral container. Ledger/backlog updates are part of the work, not optional.
6. Niche changes, account identity changes, and enabling scheduled/auto-posting are user
   decisions — propose, don't do.

## Tool crib (Higgsfield MCP)
- Video: `generate_video` (models: `seedance_2_5` 4–30s + audio, `flux_3_video` 5–20s + synced audio, `gemini_omni_flash_1_1` 3–10s, `minimax_h3_max` fast/cheap) · batch via `generate_video_batch` → `jobs_wait` → `show_generation_by_ids`
- Full shorts pipeline: `shorts_studio_create` (+ `shorts_studio_list_presets`, `shorts_studio_status`)
- Quality gate: `virality_predictor` · Audio/VO: `generate_audio` · Upscale: `upscale_video`
- TikTok: `tiktok_accounts` → `tiktok_connect` (OAuth, user clicks) → `tiktok_prepare_publish` (drafts) → `tiktok_publish_status` · trends: `tiktok_music_trending`
- Account: `balance`, `show_plans_and_credits` (only when user wants to buy)

## Current phase
**PIVOTED to streamer-clipping (2026-09-22).** Handle: **@chat.clip.that** (see
`config/account.json`). Editing pipeline validated in-container. **Network policy
FLIPPED and verified open 2026-09-23** — ingest unblocked; matrix + validated ffmpeg
recipes + in-chat browser recipe in `docs/CAPABILITY-NOTES.md`. STRATEGY/OPERATIONS/
SETUP docs still describe the legacy POV-history plan; restructure them for the
clipping model during the next work session.

**Campaign shortlist DONE (2026-09-23):** `research/whop-campaigns-2026-09-23.md`
(+ raw JSON snapshot). Top picks: CoD MW4 trailer ($2/1K), Coinbase x Valorant
($1.50/1K, fresh-page friendly), [US] Double Date Island ($2.80/1K), Crazy Taxi CNT
($2.10/1K), Candid Club ($1.20/1K). Nothing joined — joining is the user's move.

Next session:
1. Once user has joined campaign(s): build `scripts/clipper.py` around the validated
   recipe: ingest (campaign source folders / yt-dlp) → transcript (platform subs, else
   faster-whisper) → moment selection → cut → 9:16 blur-pad → ASS captions → logo
   watermark (most brand campaigns require it) → loudnorm → frame-grid QC → deliver via
   file send. Bake in the compliance checklist from the research doc (§common patterns).
2. Restructure docs for clipping; retool ledger fields for per-campaign earnings.
3. Still user-gated: Whop campaign joins + Shuffle application decision, TikTok
   `tiktok_connect`, posting (drafts/files only — user posts).
Money model: Whop-style campaign bounties (~$0.20–$6 per 1k verified views). Clip ONLY
campaign-authorized material — never freelance-clip a creator without a program.

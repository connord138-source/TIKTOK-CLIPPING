# CLAUDE.md — Operator Brief

This repo is the brain and state store for a TikTok **streamer-clipping** business
operated by Claude sessions. Claude does the production work in-container
(ingest VOD section → transcript → pick moment → cut/caption → QC → deliver files →
log → push); campaign bounties pay per verified view. Higgsfield MCP tools are
optional garnish (AI VO/b-roll), not the pipeline.

## Source of truth
- `config/account.json` — operating config (cadence, budget caps, publish mode, style)
- `config/campaigns.json` — joined campaigns + their rules (empty until user joins one)
- `content/backlog.json` — clip queue (see `content/README.md`); POV-history ideas archived
- `ledger/videos.json` — every clip's lifecycle + earnings + any credit costs (via `scripts/ledger.py`)
- `scripts/clipper.py` — the validated pipeline CLI (doctor/probe/ingest/transcribe/moments/cut/qc/pack)
- `docs/OPERATIONS.md` — the session runbook. Follow it for any production/metrics session.

## Hard rules (do not violate without the user changing config or saying so in-session)
1. **Never direct-publish to TikTok.** Prepare drafts only (`tiktok_prepare_publish`); the
   user taps post from the TikTok app. `publish_mode` in config governs this.
2. **Budget guardrails before generating:** check `mcp__HIGGSFIELD__balance`. Stop
   generating if balance would drop below `budget.balance_floor_credits`; never spend more
   than `budget.session_cap_credits` in one session; max 1 regeneration per weak concept.
3. **Log every credit.** Each generation's actual cost goes into the ledger entry
   (`credits_spent`). Update the cost table in `docs/OPERATIONS.md` when real numbers land.
4. **Content safety for account survival:** clip ONLY campaign-authorized creators —
   never freelance-clip without a program. Real editorial on every clip (own hook,
   captions, cut points), never raw re-uploads. AI-generated label ON whenever a clip
   contains an added AI element (AI VO, generated b-roll); plain edits of human footage
   are not labeled AI. See STRATEGY.md → Risks.
5. **End every session with commit + push** to the working branch so state survives the
   ephemeral container. Ledger/backlog updates are part of the work, not optional.
6. Niche changes, account identity changes, and enabling scheduled/auto-posting are user
   decisions — propose, don't do.

## Tool crib
**Primary (no credits):** `scripts/clipper.py` — doctor / probe / ingest / transcribe /
moments / cut / qc / pack; media stays in gitignored `work/`. Ledger:
`scripts/ledger.py` add/set/list/report (campaign earnings aware).

### Higgsfield MCP (optional garnish + legacy lane)
- Video: `generate_video` (models: `seedance_2_5` 4–30s + audio, `flux_3_video` 5–20s + synced audio, `gemini_omni_flash_1_1` 3–10s, `minimax_h3_max` fast/cheap) · batch via `generate_video_batch` → `jobs_wait` → `show_generation_by_ids`
- Full shorts pipeline: `shorts_studio_create` (+ `shorts_studio_list_presets`, `shorts_studio_status`)
- Quality gate: `virality_predictor` · Audio/VO: `generate_audio` · Upscale: `upscale_video`
- TikTok: `tiktok_accounts` → `tiktok_connect` (OAuth, user clicks) → `tiktok_prepare_publish` (drafts) → `tiktok_publish_status` · trends: `tiktok_music_trending`
- Account: `balance`, `show_plans_and_credits` (only when user wants to buy)

## Current phase
**Pipeline BUILT + VALIDATED E2E (2026-09-22, network open).** Handle:
**@chat.clip.that**. Twitch VOD → whisper transcript → 9:16 captioned clip proven on
real material (26s clip in 24s wall; details + connectivity matrix in
`docs/CAPABILITY-NOTES.md`). Docs/ledger/config restructured for clipping. YouTube
media ingest stays bot-checked (user-cookie workaround documented; don't re-test idly).

**PRODUCTION LIVE (2026-09-23).** TikTok @chat.clip.that created. First active
campaign in `config/campaigns.json`: **cod-mw4-trailer** ($2/1k) — its official 4K
trailer + logo assets downloaded from the campaign Drive folder (gdown works); first
clips cut. Open campaigns have NO join step ("Submit clip" only): produce → user
posts → user submits post URL on the campaign page (see OPERATIONS §C). Shortlist +
full rules: `research/whop-campaign-shortlist-2026-09-23.md`,
`config/campaigns-proposed.json` (next up: Coinbase×Valorant — user must grab its
Dropbox link + warm-up doc from the Notion rules). Keyless discovery:
`whop_scout.py discover / detail`. Campaign-authorized material only, as ever.

**MISSION CONTROL LIVE (2026-09-26).** The dashboard is now a live app (artifact URL in
`config/dashboard.json`; capabilities db+assets+downloads): the user taps **Queue a
clip** on an open campaign → the hourly `clip-queue-watcher` Routine produces it per
`docs/PRODUCE-QUEUE.md` and posts video + posting package back onto the board; the
2x-daily pool guard keeps pools/board synced and mirrors "posted" marks into the
ledger. Data flows through the artifact DATABASE (ArtifactData), never HTML edits.
Posting/submitting stays human, as ever. Since 09-26 the 2x-daily run also AUTO-FINDS
campaigns (`whop_scout.py board-feed`: gaming/streamer only, ranked by money) and TRACKS
TikTok views live (`scripts/tiktok_stats.py`, public profile via yt-dlp + curl_cffi);
queued `cr-*` campaigns get onboarded by the watcher (PRODUCE-QUEUE §2.5).

Session start ritual: bootstrap installs + `python3 scripts/clipper.py doctor`
(fresh containers lose ffmpeg/yt-dlp/whisper; ~1 min to restore). Then follow
OPERATIONS.md. Money model: campaign bounties ~$0.20–$6 per 1k verified views;
marginal cost per clip ≈ $0.

# CLAUDE.md — Operator Brief

This repo runs a **GTA 6 TikTok clip page** (@chat.clip.that). Code in `clipfarm/` does the
production (scout → moments → render → QC → analytics), a localhost dashboard (`web/`) is the
user's control room, and Claude sessions operate it via the CLI and the agents in
`.claude/agents/` (`/farm` runs a full session).

## Source of truth
- `config/account.json`: niche, cadence phases, scout queries, render/brain/autopilot settings
- `config/sources.json`: creators with **rights levels** + paid clipping campaigns
- `data/clips.json`, `data/candidates.json`, `data/metrics.json`, `data/trends.json`: state
- `docs/STRATEGY.md` (why), `docs/OPERATIONS.md` (runbook), `docs/SETUP.md`, `docs/CAPABILITY-NOTES.md`
- CLI: `python -m clipfarm --help` · tests: `python -m pytest -q tests`
- Commands: `/farm` (scout, produce, analyse) · `/drafts` (approved clips → TikTok drafts)
- Clip statuses: `rendering → rendered → approved → drafted → posted` (or `rejected` / `failed`)

## Hard rules (do not violate without the user changing config or saying so in-session)
1. **Never post to TikTok.** Clips are delivered as files or TikTok drafts; the user posts.
   `publish_mode` governs this. Autopilot never posts. With Higgsfield, the mode is always
   `UPLOAD_TO_DRAFT`, never `DIRECT_POST`, and the user submits the publish form themselves.
2. **Rights gate.** Only `campaign | permission | own` sources auto-render. Never set a channel to
   campaign/permission unless the user confirms they joined that program or have permission.
3. **Brand safety.** Keep the NSFW filter on; no sexual content, no leaks, no real-person
   impersonation, no implied Rockstar affiliation.
4. **AI label.** Real gameplay clips are NOT AI-generated, so the label stays off. Turn it ON for any clip
   that includes AI-generated visuals or voice (e.g. Higgsfield intros).
5. **Budgets.** Higgsfield: check `balance`, respect `budget.*` caps. Claude brain: keep
   `brain.effort` at medium unless the user asks.
6. **End every session with commit + push** to the working branch (data/, config/, docs/).
7. Niche changes, account identity (handle) changes, cadence targets, enabling
   `cadence.auto_adjust.apply` or `produce.auto_approve` are user decisions: propose, don't do.

## Current phase
**GTA 6 launch surge (2026-11-19 → 12-03), 5 posts/day.** Engine + dashboard + agents built and
tested 2026-11-18. Cloud sessions can scout/plan/analyse; rendering YouTube sources needs the
user's machine (googlevideo blocked + datacenter bot-checks; see CAPABILITY-NOTES).
User-gated next steps: run locally (`docs/SETUP.md`), add ANTHROPIC_API_KEY, join GTA 6
clipping programs for the creators the scout surfaces most, then "Trust channel" them.

## Tool crib (Higgsfield MCP: optional now)
- TikTok drafts (`/drafts` runs this): `tiktok_accounts` (account is connected and active) →
  `media_upload` → curl PUT the clip → `media_confirm` → `tiktok_prepare_publish` with
  `UPLOAD_TO_DRAFT` → **the user submits the form** → `tiktok_publish_status`. The video must be
  Higgsfield-hosted, and the session needs to read `media/clips/` (the user's computer).
- `tiktok_music_trending` for trending sounds · Upscale: `upscale_video` · Quality gate: `virality_predictor`
- AI intros (label ON): `generate_video` (`seedance_2_5`, `flux_3_video`, …) · `generate_audio`
- Account: `balance`, `show_plans_and_credits` (only when the user wants to buy)

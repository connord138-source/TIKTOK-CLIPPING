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
- Commands: `/farm` (scout, produce, analyse) · `/drafts` (Higgsfield fallback for TikTok drafts)
- Dashboard does the rest: Connections tab holds keys (stored in `data/secrets/`, gitignored)
  and the TikTok login; **Send to TikTok drafts** uploads approved clips via TikTok's API
- Clip statuses: `rendering → rendered → approved → drafted → posted` (or `rejected` / `failed`)
- `clipfarm/niches.py`: what gets clipped (searches, relevance words, hashtags, a brief for
  Claude). GTA 6 is the default; more are added in the dashboard's Niches tab.
- `clipfarm/accounts.py`: where clips go, each with its own niches and posts per day.
  Two kinds: a TikTok login through our own app (drafts only), and an Upload-Post profile
  (`via: "uploadpost"`, posts to TikTok + Reels + Shorts). `planner.plan()` plans per account.
- `clipfarm/uploadpost.py`: profiles sync, scheduling clips at slot times with captions,
  status polling, cancel. Clip status `scheduled` = handed to Upload-Post, not live yet.
- `clipfarm/notify.py`: the "clips ready" email, one per run, from the user's own Gmail to
  itself (set up in Connections). The subject must keep starting with exactly
  `[Clip Farm] Clips ready`: another of the user's Claude channels watches Gmail for it. The
  body carries the count and each clip's niche and account, and never a link, id or code.
  The test button uses a different subject on purpose.

## Hard rules (do not violate without the user changing config or saying so in-session)
1. **Posting.** The user dropped the never-post rule on 2026-11-25 and chose Upload-Post as
   the posting service. Public posting goes only through `clipfarm/uploadpost.py`, and only
   for a profile whose "Post automatically" switch the user turned on (off by default), or
   when the user clicks "Post now". Never flip that switch for them. `clipfarm/tiktok.py`
   stays on TikTok's inbox (draft) endpoint: do not add TikTok's direct-post endpoint there,
   because TikTok will not approve a personal uploader app and it could only ever post privately.
2. **Rights gate.** Only `campaign | permission | own` sources auto-render, unless the user has
   turned on `produce.include_unverified` ("Clip trending videos from any creator") in the
   dashboard. That switch is theirs: never flip it, and never set a channel to
   campaign/permission unless the user confirms they joined that program or have permission.
3. **Brand safety.** Keep the NSFW filter on; no sexual content, no leaks, no real-person
   impersonation, no implied Rockstar affiliation.
4. **AI label.** Real gameplay clips are NOT AI-generated, so the label stays off. Turn it ON for any clip
   that includes AI-generated visuals or voice (e.g. Higgsfield intros).
5. **Budgets.** Higgsfield: check `balance`, respect `budget.*` caps. Claude brain: keep
   `brain.effort` at medium unless the user asks.
6. **End every session with commit + push** to the working branch (data/, config/, docs/).
7. Niche changes, account identity (handle) changes, cadence targets, and the switches
   `cadence.auto_adjust.apply`, `produce.auto_approve`, `produce.include_unverified` and
   `tiktok.auto_send` are user decisions: propose, don't do. The dashboard's "Turn on full
   auto" button is how the user turns the last three on.
8. **Don't commit changes to `config/*.json` or `data/*.json`.** The user's dashboard rewrites
   those files on their PC, so an upstream change makes their `git pull` fail. New settings
   get their default in code (`cfg.get(..., default)`).

## Current phase
**GTA 6 launch surge (2026-11-19 → 12-03), 5 posts/day.** The user runs the farm on their
Windows PC (Python 3.14). Done there: Claude key saved, TikTok connected with `video.upload`
through the https forwarding page (`docs/tiktok-callback/` on GitHub Pages; TikTok's portal
refuses local redirect addresses). Proven on their PC as of 2026-11-25: YouTube download,
render, and real uploads arriving in TikTok drafts. Cloud sessions can scout/plan/analyse;
rendering YouTube sources needs the user's machine (googlevideo blocked + datacenter bot-checks).

How moments are chosen: candidate windows come from captions, replay data or audio loudness
(`moments.audio_energy` for no-commentary gameplay); Claude then sees four frames from each
window (`moments.window_previews` → `brain.pick_moments`) and picks or rejects; each rendered
clip gets a final visual check (`brain.review_clip`, auto-approve needs quality ≥ 70).

Captions cannot travel with a TikTok draft (the inbox API takes only the video). The phone
page (`clipfarm/phone.py`, switch + QR in Connections) shows them on the user's phone over
Wi-Fi. `serve` listens on the network for that page only: anything else from another device,
and every POST, is refused. Keep it that way.

Scale goal (2026-11-25): 200-300 clips a week across several accounts and platforms, not only
GTA. Built: niches, multiple accounts, and Upload-Post posting (TikTok, Reels, Shorts).
The Upload-Post code was written from its docs and tested against a local stand-in only: the
first real upload with the user's API key is the real test (response field names for links
and statuses are the likeliest thing to need adjusting).

Open feedback from the user (2026-11-25): clips were picking boring moments (visual picking
added in response, not yet confirmed better) and word captions "need work" (specifics not
yet known: ask for an example before changing caption rendering).

## Tool crib (Higgsfield MCP: optional now)
- TikTok drafts (`/drafts` runs this): `tiktok_accounts` (account is connected and active) →
  `media_upload` → curl PUT the clip → `media_confirm` → `tiktok_prepare_publish` with
  `UPLOAD_TO_DRAFT` → **the user submits the form** → `tiktok_publish_status`. The video must be
  Higgsfield-hosted, and the session needs to read `media/clips/` (the user's computer).
- `tiktok_music_trending` for trending sounds · Upscale: `upscale_video` · Quality gate: `virality_predictor`
- AI intros (label ON): `generate_video` (`seedance_2_5`, `flux_3_video`, …) · `generate_audio`
- Account: `balance`, `show_plans_and_credits` (only when the user wants to buy)

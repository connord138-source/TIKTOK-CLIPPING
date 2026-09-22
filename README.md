# tiktok-clipping

An AI-operated streamer-clipping business. Claude cuts campaign-authorized VOD moments
into captioned 9:16 clips in the cloud container; campaign bounties pay per verified
view; this repo keeps the state so every session picks up exactly where the last one
left off.

## How it works
1. **Campaigns** (Whop-style creator programs) live in `config/campaigns.json` with
   their rates and rules. No campaign → no clip.
2. **Clip sessions** (Claude + `scripts/clipper.py`): ingest a VOD section → whisper
   transcript → pick the moment editorially → cut to 9:16 with blur-pad, burned hook +
   accent caption cards, loudnorm → QC via frame grid → deliver finished MP4 + post
   text to the user.
3. **You** post from the TikTok app (@chat.clip.that) — human on the trigger, and
   campaigns require account-holder posting anyway.
4. **Ledger** tracks every clip: source VOD window, campaign, views, verified views,
   USD earned/paid. Metrics sessions tune the campaign mix.

## Layout
```
CLAUDE.md             operator brief + hard rules for Claude sessions
docs/STRATEGY.md      money model, campaign selection, algorithm playbook, risks
docs/OPERATIONS.md    clip/metrics/onboarding session runbooks
docs/SETUP.md         one-time checklist (what only the user can do)
docs/CAPABILITY-NOTES.md  validated pipeline recipes + connectivity matrix
config/account.json   operating config (cadence, budget caps, publish mode, style)
config/campaigns.json joined campaigns + rules (the authorization list)
content/              clip queue + archived POV-history backlog
ledger/               videos.json = every clip: lifecycle, earnings, metrics
scripts/clipper.py    the pipeline CLI (doctor/probe/ingest/transcribe/moments/cut/qc/pack)
scripts/ledger.py     ledger CLI (add / set / list / report, campaign-aware)
work/                 (gitignored) per-job media: sources, clips, grids, transcripts
```

## Status
- Phase: **pipeline validated end-to-end** (2026-09-22) — network open, Twitch ingest +
  whisper + render proven on real material
- Waiting on user: join first Whop campaign(s) · create TikTok @chat.clip.that
- Higgsfield: Plus plan, ~461 credits — optional garnish only; clipping burns none

No frontend by design — `python3 scripts/ledger.py report` is the dashboard until
there's real earnings data worth visualizing.

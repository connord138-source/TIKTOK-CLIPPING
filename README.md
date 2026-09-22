# tiktok-clipping

An AI-operated TikTok short-form content business. Higgsfield generates the videos,
Claude runs the pipeline, this repo keeps the state so every session picks up exactly
where the last one left off.

## How it works
1. **Ideas** live in `content/backlog.json`, scored and pre-planned.
2. **Production sessions** (Claude + Higgsfield MCP): pick top ideas → script → generate
   9:16 video with native audio → quality-gate with the virality predictor → prepare as a
   TikTok **draft** → log everything in the ledger.
3. **You** tap "post" on drafts from the TikTok app (keeps a human on the trigger),
   and the next metrics session pulls performance back into the ledger.
4. **Iterate:** double down on the top-performing formats, kill the rest.

## Layout
```
CLAUDE.md            operator brief + hard rules for Claude sessions
docs/STRATEGY.md     monetization paths, niche analysis, algorithm playbook, risks
docs/OPERATIONS.md   the production/metrics session runbook + cost table
docs/SETUP.md        one-time setup checklist + account status
config/account.json  operating config (niche, cadence, budget caps, publish mode)
content/backlog.json scored idea backlog
ledger/              videos.json = every video: lifecycle, credits, metrics
scripts/ledger.py    CLI for the ledger (add / set / list / report)
```

## Status
- Phase: bootstrap complete, pre-launch
- Recommended niche: **POV History** (immersive first-person 60–75s) — awaiting confirmation
- TikTok: not yet connected · Higgsfield: Plus plan, 461 credits (2026-09-22)

No frontend yet by design — `python3 scripts/ledger.py report` is the dashboard until
there's real data worth visualizing (then: published dashboard artifact or a Worker).

# tiktok-clipping — GTA 6 clip farm

A semi-autonomous TikTok clip page for **GTA 6**. Agents find the moments, the pipeline cuts
them into captioned 9:16 clips, a localhost dashboard shows the queue and TikTok analytics,
and a human approves and posts.

```
scout ──► candidates ──► produce ──► review ──► post (you) ──► metrics ──► planner/advisor
YouTube    rights gate    Claude picks   dashboard   phone /       TikTok stats    cadence ±1,
Twitch     + NSFW filter  moments, then  approve/    TikTok        → clips,        breakouts,
URLs       + velocity     ffmpeg + QC    edit hook   Studio        earnings        trend queries
```

## Quick start
```bash
pip install -r requirements.txt && python -m clipfarm doctor
```
```bash
python -m clipfarm serve
```
→ http://127.0.0.1:8787 · **step-by-step: `docs/START-HERE.md`** · keys: `docs/SETUP.md`

## Layout
```
clipfarm/            the engine (stdlib + yt-dlp + ffmpeg; anthropic SDK optional)
  scout.py           YouTube/Twitch discovery, velocity scoring, NSFW filter
  moments.py         captions + heatmap + keyword windows → Claude picks moments
  brain.py           Claude calls (structured outputs, refusal fallback); heuristics if absent
  render.py          section download → 1080×1920 layouts, ASS captions, loudnorm, QC grid
  analytics.py       TikTok public / Display API / CSV → metrics, auto-linking, earnings
  tiktok.py          TikTok login (PKCE) + upload to the user's inbox/drafts + posted sync
  planner.py         cadence phases, slot board, production need, performance advisor
  pipeline.py        workflows (scout/produce/metrics/cycle), job runner, autopilot
  server.py          localhost JSON API + media streaming + TikTok OAuth
web/                 dashboard (vanilla JS, no build step)
config/account.json  niche, cadence, scout queries, render + brain + autopilot settings
config/sources.json  creators/channels with rights levels, paid campaigns
data/                clips.json · candidates.json · metrics.json · trends.json (tracked state)
.claude/agents/      gta-scout · clip-editor · growth-analyst   (+ /farm command)
docs/                STRATEGY · OPERATIONS · SETUP · CAPABILITY-NOTES
tests/               pytest suite incl. an end-to-end render
```

## Status (2026-11-18)
GTA 6 launches **Nov 19, 2026**. Launch-surge cadence: **5 posts/day** through Dec 3.
Engine, dashboard and agents are built and tested. The first real renders need the user's
machine (YouTube media is blocked from the cloud container).

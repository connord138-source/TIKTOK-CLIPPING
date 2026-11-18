# Operations runbook — GTA 6 clip farm

Two ways the farm runs. Both use the same code (`clipfarm/`) and state (`data/`, `config/`).

## A. On your machine (primary)
```bash
python -m clipfarm serve        # http://127.0.0.1:8787
```
- **Today** tab: today's slot board. Each assigned slot has Download / Copy caption / Posted.
  Post from your phone or TikTok Studio, then hit Posted (paste the TikTok URL if handy; the
  metrics pull auto-links it by caption otherwise).
- **Review** tab: approve or reject rendered clips, edit the hook, and Re-render to burn it in.
- **Scout** tab: the "Needs your call" list holds high-score sources from creators without a
  known program. Use **Trust channel** once you've joined their program or have permission,
  and every future upload from them auto-clips. "Clip a specific URL" covers campaign source
  links and your own captures.
- **Autopilot** toggle: scouts every 2h, produces when the queue is short, pulls metrics
  every 6h, and cleans work files daily. It never posts.

Daily rhythm (~15 min): morning review (approve 5–7) → post at the slot times →
evening glance at Analytics. Weekly: join the 1–2 campaigns or programs for creators the
scout surfaces most.

## B. Claude Code session (`/farm`)
`/farm` runs: doctor/status → **gta-scout** (CLI scout + web trend research + campaign hunt)
→ **clip-editor** (produce + frame-grid QC + hook fixes) → **growth-analyst** (metrics →
`docs/INSIGHTS.md`) → commit + push. Agents live in `.claude/agents/`.

Cloud-session caveat: YouTube's media CDN (`*.googlevideo.com`) is blocked by this environment's
network policy and YouTube bot-checks datacenter IPs, so **cloud sessions can scout, plan and
analyse, but rendering YouTube sources needs your machine** (Twitch is the same: clip CDN
untested). See `docs/CAPABILITY-NOTES.md`.

## C. Sending clips to TikTok drafts
**From the dashboard (primary).** After the one-time setup in the Connections tab (a TikTok
developer app with Login Kit + Content Posting API, see `docs/START-HERE.md` B4a), every
approved clip has a **Send to TikTok drafts** button, and Today has **Send all ready clips**.
The farm uploads through TikTok's inbox endpoint, marks the clip `drafted`, and marks it
`posted` on its own once you publish it from TikTok (checked every 5 minutes). Limits: 5
unposted drafts per 24 hours, and captions are added in the TikTok app.

**Through Claude and Higgsfield (fallback, `/drafts`).** No TikTok developer app needed:
1. Approve clips in the dashboard as usual.
2. In a Claude session **on the computer that has the clips**, opened on this folder, type `/drafts`.
3. Claude uploads each clip to Higgsfield and shows one TikTok form per clip. Submit each form.
4. The clips show as **in TikTok drafts** on the Today tab. Open TikTok, paste the caption if it
   isn't there, and post at the slot time. Click **Posted** in the dashboard.

It can't be fully automatic: Higgsfield requires the account owner to submit the form for every
clip, and only a Claude session (not the Python farm) can call Higgsfield.

## Pipeline (what each workflow does)
| Workflow | Steps |
|---|---|
| scout | YouTube date-filtered search over `scout.queries` + Claude trend queries → top-K full metadata (upload time, channel, captions, "most replayed" heatmap) · Twitch: Helix top GTA VI clips (if keys) + watchlist channel clips · score = view velocity + recency + relevance + rights − unsafe |
| produce | planner says how many → pick best rights-cleared candidates (2/creator/day) → captions (YouTube json3 word timings, or faster-whisper) → windows (heatmap + speech energy + excitement/GTA keywords, capped) → **Claude picks 1–2 moments, refines bounds, writes hook/caption/hashtags** → render 1080×1920 (blur-pad / zoom / facecam split) → QC (probe, loudness, black frames, 6-frame grid) → `rendered` |
| metrics | TikTok public profile (yt-dlp) or Display API (OAuth) or CSV → snapshots → link posts to clips → campaign earnings |

Statuses: candidate `new → queued → processing → processed | skipped | failed | needs_rights`;
clip `rendering → rendered → approved → drafted (optional) → posted | rejected | failed`.

## Hard rules (also in CLAUDE.md)
- Draft/file delivery only. The user posts. Never auto-post.
- Rights gate: only `campaign | permission | own` auto-render. Never upgrade a channel's rights
  without the user confirming they joined the program.
- Brand safety filter stays on. No sexual content.
- Every session ends with commit + push of `data/`, `config/`, `docs/`.

## Costs
- Claude brain: ~1 call per source (moment pick) + 1 trend-query call per 6h. Opus 5.5 at
  medium effort, roughly $0.01–0.03 per source at ~5k input tokens. Switch `brain.enabled`
  off to run on heuristics only.
- Higgsfield credits: now optional (AI intros/upscales only). Budget caps in
  `config/account.json → budget` still apply.

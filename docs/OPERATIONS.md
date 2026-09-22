# Operations Runbook — clipping

How a Claude session runs this business. Every session ends with ledger/docs updated,
committed, pushed (hard rule 5).

## A. Clip production session (default)

1. **Bootstrap** (fresh container): `apt-get update -qq && apt-get install -y -qq ffmpeg;
   pip3 install -q yt-dlp faster-whisper`, then `python3 scripts/clipper.py doctor`.
   Any BLOCKED host → stop, tell the user (policy regressed).
2. **Load state:** `config/account.json`, `config/campaigns.json`,
   `python3 scripts/ledger.py report`.
3. **Pick campaign + source:** active campaign from `campaigns.json` (status
   `active`, pool not drained). Source = campaign-provided folder/links, else the
   creator's VOD listing (`clipper.py probe`). **No active campaign → stop; clipping
   unauthorized material is forbidden.**
4. **Ingest smart:** don't pull whole VODs. Use chat knowledge/campaign pointers to
   pick 10–20 min windows around likely moments:
   `clipper.py ingest URL --section H:MM:SS-H:MM:SS --quality 720p --campaign <id>`
   (1080p for source-quality campaigns; 720p is the throughput default).
5. **Find the moment:** `clipper.py transcribe` → read `transcript.txt` yourself;
   `clipper.py moments` is an assist, not a decision. Pick 15–45s arcs: setup →
   spike → reaction. Note exact section-local start/end.
6. **Cut:** `clipper.py cut --start S --end E --hook "PAYOFF LINE"`. Hook states the
   payoff in ≤6 words, caps. 2–5 clips per session across 1–2 sources.
7. **QC every clip (gate):** `clipper.py qc` → **read the frame grid image**, check
   loudness ≈ −14 LUFS, captions match speech, hook not covering faces. Weak moment →
   re-pick; never ship filler.
8. **Deliver:** `clipper.py pack`; send each clip + grid + a post-text block
   (caption per campaign rules: required tags first, 2–3 topical hashtags) via file
   send. User posts from phone. AI-label only if an AI element was added.
9. **Ledger every clip:**
   `ledger.py add --title ... --campaign <id> --rate-per-1k R --source-url URL
   --vod-window H:MM:SS-H:MM:SS --clip-file work/<job>/clip-NNN.mp4 --status clipped`
   → after user confirms posting: `set vNNN status=posted posted_at=... tiktok_url=...`
10. **Commit + push** (include any campaign-rule learnings in `campaigns.json`).

Credits: this pipeline spends none. If AI garnish (VO, b-roll, upscale) is ever used,
hard rule 2 applies first (`balance`, floor 150, session cap 250).

## B. Metrics / payout session (24–48h after posts, and weekly)

1. User relays TikTok stats + campaign dashboard numbers (screenshots fine).
2. `ledger.py set vNNN views=... verified_views=... payout_status=verified|paid
   earnings_usd=...` as numbers land.
3. `ledger.py report` → per-campaign $ and views. Feed the answer back into campaign
   mix: double down where verified-view rate and acceptance are best; drop drained
   pools (mark campaign `status: "ended"` in campaigns.json).
4. Mine what worked (hook style, clip length, streamer) → note in campaigns.json
   `notes`. Commit + push.

## C. Campaign onboarding (user-gated parts marked 👤)

1. 👤 User signs up / signs in on Whop (or campaign platform) and picks campaigns
   (Claude can shortlist from public pages when asked).
2. 👤 User pastes campaign brief/rules + source links into the session.
3. Claude encodes it in `config/campaigns.json`:
   ```json
   {"id": "whop-xyz", "name": "...", "platform": "whop", "creator": "...",
    "rate_per_1k": 1.5, "pool_usd": 5000, "min_len_s": 15, "max_len_s": 60,
    "required_tags": ["@creator"], "required_sounds": null,
    "sources": ["https://..."], "allowed_platforms": ["tiktok"],
    "status": "active", "joined_at": "...", "notes": ""}
   ```
4. First clip of a new campaign: extra-careful rules pass, then normal flow.

## Session boundaries
- Draft/file-only delivery — the user posts. `publish_mode` in config governs; do not
  change it in-session.
- TikTok connect (`tiktok_connect`) is optional QoL for `tiktok_prepare_publish`
  drafts later; the file-send loop works without it.
- Scheduled/recurring sessions stay OFF until the user opts in.

## Automation ladder (agreed direction, 2026-09-22)
Target end state: user approves campaigns and taps post; everything between is
automatic. Two human touchpoints by design.
1. **NOW (manual trigger):** user-run clip sessions → files delivered → user posts.
2. **Scheduled production** (user opt-in, ready to enable): daily Routine wakes a
   session → full clip flow → files + ledger + push. No credits burned.
3. **Staged drafts:** after user runs `tiktok_connect` once, deliver via
   `tiktok_prepare_publish` → clips wait in the user's TikTok inbox; user taps post.
   Metrics sessions then pull views automatically.
4. **Campaign auto-discovery** (needs one investigation session): Whop developer API
   key (dashboard → Developer) or user-exported cookies → poll Content Rewards →
   filter by STRATEGY §3 criteria → write PROPOSED entries to campaigns.json. User
   still clicks Join (terms/applications are theirs to accept).
5. **NOT planned near-term — full auto-post:** technically feasible once connected,
   but new-account distribution risk + "mass-produced content" flag risk + many
   campaigns require account-holder posting. User decision per hard rule 6; revisit
   only once the account is established and a campaign's terms allow it.

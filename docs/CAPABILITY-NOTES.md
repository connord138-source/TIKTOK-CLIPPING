# Capability notes — clipping pipeline (network OPEN, validated 2026-09-22)

The environment network policy was flipped and re-verified in-session. `scripts/clipper.py
doctor` now automates the tooling + connectivity check — run it at the start of every
production session (fresh containers lose apt/pip installs).

## Session bootstrap (fresh container)
```
apt-get update -qq && apt-get install -y -qq ffmpeg   # stale apt index 404s without update
pip3 install -q yt-dlp faster-whisper
python3 scripts/clipper.py doctor                     # verifies tools, fonts, network
```
whisper `small.en` (int8) downloads from huggingface on first use (~10s, cached in
container only — re-downloads each fresh container).

## Connectivity matrix (validated 2026-09-22 post-flip)
| Path | Result |
|---|---|
| Twitch VOD list + media (`ttvnw.net`/`cloudfront.net` HLS) | ✅ **validated E2E** — 2min/720p section in ~7s (≥20x realtime); full ladder to 1080p60 Source |
| Kick VOD listing | ✅ works via yt-dlp (Cloudflare passes datacenter IP) — media download not yet exercised |
| YouTube metadata/subs listing | ✅ works |
| YouTube media download | ❌ **bot-check** ("Sign in to confirm you're not a bot"), also on tv/mweb clients. Workarounds: user-exported browser cookies (`--cookies`), PO tokens, or campaign-provided files. Revisit only if a campaign needs YouTube source |
| Direct media URL (HTTP range) | ✅ archive.org 206 partial-content verified; ffmpeg remote range-seek recipe applies |
| Drive/Dropbox (campaign folders) | Hosts reachable (302/200); full download untested until a real campaign link exists |
| huggingface.co (whisper models) | ✅ validated — small.en pulled + run |
| whop.com / contentrewards.com | ✅ 200 |
| Agent proxy | healthy, `"selective": false` (full egress). BigBuckBunny GCS bucket 403 is Google's own AccessDenied (bucket privated), not policy |

## Editing pipeline: VALIDATED end-to-end via `scripts/clipper.py`
Twitch VOD → `ingest` (section download) → `transcribe` (whisper small.en, word
timestamps, 3.6x realtime cpu) → `moments` (heuristic assist) → editorial pick →
`cut` (9:16 blur-pad + ASS caption cards w/ accent word + hook + loudnorm I=-14) →
`qc` (frame grid Claude reads + ffprobe + ebur128) → `pack` → file send.
**26s clip rendered in 24s wall** (≈1x realtime, 4-core). Measured loudness −14.6 LUFS.

Validated filter chain (lives in `cmd_cut`):
```
[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=24[bg];
[0:v]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[comp];[comp]subtitles=<clip>.ass[v]
-map [v] -map 0:a? -af loudnorm=I=-14:TP=-1
-c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p -c:a aac -b:a 128k -movflags +faststart
```

## Transcript sources by platform
- **Twitch/Kick:** no platform subs → faster-whisper is the primary path (validated).
- **YouTube:** auto-sub VTT with word timings when media access exists (`parse_vtt_words`).
- Word timestamps drive the caption cards; segment text drives moment selection.

## Headless browsing (tested 2026-09-22): cert-blocked, don't re-burn time
Playwright + preinstalled Chromium (`/opt/pw-browsers/chromium`) fails all HTTPS with
`ERR_CERT_AUTHORITY_INVALID` — the agent proxy's CA is not honored even after adding it
to the NSS store (`certutil -d sql:/root/.pki/nssdb -A -t "C,," -n agentproxy-ca -i
/root/.ccr/ca-bundle.crt`; this build seems to use its own root store exclusively).
Never disable TLS verification. Consequence: JS-rendered pages (Whop discover, TikTok
web) can't be scraped headlessly for now; curl/yt-dlp/pip/ffmpeg trust the proxy fine.
Whop discover HTML is a client-rendered shell with no campaign data server-side —
campaign details come from the user pasting them (OPERATIONS §C).

## Keyless campaign discovery VALIDATED (2026-09-23)
`GET https://contentrewards.com/api/campaign/campaigns/discover` — public, no auth,
works in-container. Cursor pagination (`?cursor=<pagination.nextCursor>`), ~20/page,
300 campaigns fetched live. Fields: cpmMin/MaxRateCents, budgetCents,
metrics.budgetSpentCents, organizationName/Verified, payoutType. Detail at
`/discover/{id}` (adds description + payouts). Wrapped by `whop_scout.py discover` /
`detail`. Numbers cross-validated against the desktop session's browsing research.

## Whop API mapped (2026-09-23) — Content Rewards = "bounties"
Base `https://api.whop.com/api/v1`, `Authorization: Bearer <key>`; full OpenAPI spec
mirrored from the docs CDN. Discovery: `GET /bounties?status=open&
business_goal_type=clipping&order=gross_reward_amount&direction=desc` (cursor
pagination first/after). Bounty fields incl. `budget_amount`, `gross_reward_amount`,
`gross_paid_out_amount` (pool health), `spots_remaining`,
`min_total_verified_duration_seconds`, `accepted_deliverable_types`, `description`
(rules text; per-1k rate likely lives here — confirm on first real payload).
Submission leg exists: `POST /bounty_submissions` → `POST /bounty_submissions/{id}/
submit` (programmatic payout claim on posted clips — later automation).
Unauthenticated list → 400 "must provide a valid App API key". **Key-type semantics
VERIFIED 2026-09-26:** `WHOP_CLIPPING` is company-scoped — `/bounties` returns 0 (only
bounties we'd run), and a marketplace campaign id (Valorant `3cd86bbc…`) → 404 "Bounty
not found" on both `show` and `submissions`. So programmatic "Submit clip" is NOT
possible with this key; the button runs on the user's logged-in browser session. Only
route would be borrowed browser cookies against the site's internal API (brittle,
touches the payout account) — rejected; submission stays manual.
`scripts/whop_scout.py` (probe/scout/show/submissions) wraps all of this; scans that
return 0 rows no longer overwrite `config/campaigns-discovered.json`.
**Key delivery:** user set `WHOP_CLIPPING`; GitHub repo secrets are NOT visible here —
it must be a cloud-environment Environment variable, and those reach sessions STARTED
AFTER saving (same rule as the network policy flip).

## Residual risks / open items
- Kick media download not yet exercised (listing works) — validate on first Kick campaign.
- Twitch sub-only VODs exist on some channels; campaign material usually comes with
  access or files. GDQ-style public VODs download without auth.
- YouTube media stays user-gated (cookies) — don't burn session time re-testing it.
- Long VODs: ingest sections (10–20 min around candidate moments), not whole VODs —
  disk allowance is finite and `df` misleads in this container.

## Delivery loop (v1, validated mechanics)
clipper `pack` writes `deliverables.txt`; clip + QC grid go to the user via file send;
user posts from phone (campaigns generally require account-holder posting anyway).
Board delivery (2026-09-26): finished clips also live as ops-board assets with an in-page
player + Download (downloads capability).

## TikTok drafts lane (connected 2026-09-26)
- Account linked via `tiktok_connect` (OAuth opened on the phone logged into
  @chat.clip.that); connector id in `config/account.json`. Higgsfield's grant is broad
  (publish/upload/insights/comments) — we only ever use `UPLOAD_TO_DRAFT`.
- TikTok only accepts **Higgsfield-hosted** media: `media_upload` → curl PUT the bytes from
  the container (HTTP 200) → `media_confirm type=video` → the returned cloudfront `url`
  is the `video_url`. 14.4MB / 1080×1920 / 60fps / 22.5s accepted (limits: MP4/WebM/MOV,
  ≤1GB, 3–600s, ≥360px, 23–60fps — 60fps is the ceiling, so never export higher).
- `tiktok_prepare_publish` returns a publish session (~2h TTL), preview, privacy options
  (this account: PUBLIC / MUTUAL_FOLLOW_FRIENDS / SELF_ONLY), comment/duet/stitch that
  the user must select, commercial-content choice (none / your brand / branded content /
  both — branded = "Paid partnership" label, cannot be private), and required
  confirmations. **Publishing is widget-only**: the user completes the publish form in a
  Claude client that renders MCP Apps widgets; there is no programmatic publish, and a
  chat reply is never consent. Fallback when this client shows no form: a regular Claude
  chat with the Higgsfield connector, pasting the video URL + caption.
- Prefill `is_aigc=false` only for plain human-footage edits (account rule); privacy and
  disclosure are left for the user's form.

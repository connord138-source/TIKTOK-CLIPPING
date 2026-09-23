# Capability notes — clipping pipeline feasibility (validated 2026-09-22)

Findings from the in-session proof-of-capability run. Keep current: re-verify the
network matrix after any environment policy change.

## Editing: VALIDATED end-to-end in the cloud container
- ffmpeg 6.1.1 installs via apt (run `apt-get update` first — stale index 404s otherwise).
  yt-dlp installs via pip (PyPI is always reachable). DejaVu fonts present for ASS captions.
- Full render validated: remote HTTP range-seek cut (`-ss` before `-i`, no full download)
  → 9:16 blur-pad composite → burned ASS captions (styled, two-tone) → loudnorm I=-14
  → h264/aac faststart. **25s clip rendered in ~22s wall.** Throughput supports 20–30
  clips/day easily.
- Validated filter chain:
  ```
  ffmpeg -ss <start> -t <len> -i <URL-or-file> \
    -filter_complex '[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=24[bg];[0:v]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[comp];[comp]subtitles=captions.ass[v]' \
    -map '[v]' -map '0:a?' -af loudnorm=I=-14:TP=-1 \
    -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p -c:a aac -b:a 128k \
    -movflags +faststart out.mp4
  ```
- QC without watching: frame grid (`fps=1/4,scale=270:480,tile=3x2` → jpg, Claude reads it)
  + ffprobe duration/res + transcript spot-check.

## Ingest: UNBLOCKED — network policy flipped, verified 2026-09-23
Re-run of the matrix (all reachable; non-200s are normal redirects/roots):
| Host | Result |
|---|---|
| youtube.com | 301 (reachable) |
| www.twitch.tv / kick.com | 200 |
| drive.google.com / docs.google.com | 302 (reachable; public-doc export works: `/document/d/<id>/export?format=txt`) |
| dropbox.com / we.tl / app.mediasilo.com | 200/301 |
| whop.com / contentrewards.com / app.notion.com | 200 |
| huggingface.co (whisper models) | 200 |
| cdn.higgsfield.ai | 404 at root (reachable) |

yt-dlp bot-check risk on datacenter IPs still untested — validate on first real ingest.

## In-chat browser: VALIDATED 2026-09-23 (used for Whop campaign research)
Playwright 1.56.1 is global in `/opt/node22/lib` (`NODE_PATH=/opt/node22/lib/node_modules`),
Chromium under `/opt/pw-browsers`. Two gotchas, both solved:
1. **TLS**: agent proxy MITMs HTTPS; Chromium trusts NSS, and `/root/.pki/nssdb` ships
   EMPTY → `ERR_CERT_AUTHORITY_INVALID`. Fix (do once per session):
   `apt-get update && apt-get install -y libnss3-tools`, split `/root/.ccr/ca-bundle.crt`
   on `BEGIN CERTIFICATE` and `certutil -d sql:/root/.pki/nssdb -A -t "C,," -n <name> -i <pem>`
   for each cert, then start the browser. Never disable TLS verification.
2. **Persistence across Bash calls**: launch chromium via a long-lived node script with
   `args: ['--remote-debugging-port=9222']` (run_in_background; a `pkill` in the same
   command kills its own wrapper shell — exit 144). Each step then
   `chromium.connectOverCDP('http://localhost:9222')`, drives `contexts()[0]`, screenshots
   to scratchpad, and disconnects. Screenshots reach the user via file send (render).

Whop research shortcut: `contentrewards.com` is the public campaign browser — no login
needed. JSON API: `/api/campaign/campaigns/discover?limit=50&contentTag=clipping` (list;
offset param ignored, vary `sortBy`: featured/trending/newest/budget) and
`/api/campaign/campaigns/discover/{uuid}` (full detail: per-platform payouts, budget
spent, referenceMaterials, requiresApplication). Campaign reference videos live on a
public S3 bucket (`content-rewards-production-publicassetsbucket-*`) — directly
downloadable for the editing pipeline.

**Fix (user action), verified against docs 2026-09-22:** at claude.ai/code, click the
cloud icon showing the environment name in the row above the message box (no settings
page/URL exists for this) → hover the environment → gear icon → **Network access**
selector. Four levels exist: None / Trusted (current) / **Full** (any domain) / Custom.
**Recommended: Full** — media CDNs rotate hostnames (`*.googlevideo.com`,
`*.cloudfront.net`, `*.googleusercontent.com`), so Custom lists leak 403s. If Custom:
paste the list below one-per-line AND tick **"Also include default list of common
package managers"** (else apt/pip break):
```
youtube.com
*.youtube.com
*.googlevideo.com
*.ytimg.com
twitch.tv
*.twitch.tv
*.ttvnw.net
*.cloudfront.net
kick.com
*.kick.com
drive.google.com
docs.google.com
*.googleusercontent.com
storage.googleapis.com
commondatastorage.googleapis.com
dropbox.com
*.dropbox.com
*.dropboxusercontent.com
whop.com
*.whop.com
contentrewards.com
huggingface.co
*.hf.co
cdn.higgsfield.ai
*.higgsfield.ai
```
**The change applies to sessions started AFTER saving** — running sessions keep the old
policy, so start a fresh session on this repo/branch after flipping (repo state carries
everything). First new session may start slower: changing allowed hosts rebuilds the
environment snapshot. Docs: https://code.claude.com/docs/en/cloud-environments#network-access

## Residual risks after policy opens (validate on first real campaign)
- YouTube/Twitch may bot-check datacenter IPs (yt-dlp cookies/PO-token workarounds exist).
  Most reliable ingest: campaign-provided source folders (Drive/Dropbox links) — most
  Whop campaigns provide these.
- Fallback compute: Higgsfield `sandbox_exec` (their sandbox, their network) can run the
  same download+ffmpeg flow if local egress stays limited.
- ASR captions: faster-whisper via PyPI is installable, models need huggingface.co.
  Fallback: platform auto-subs via `yt-dlp --write-auto-sub` for moment-finding.

## Delivery loop (v1)
Claude produces finished MP4 + caption/hashtag text → sends files in-session → user posts
from phone (~1 min/clip; campaigns generally require account-holder posting anyway).
Later option: push clip to repo/release → `media_import_url` → `tiktok_prepare_publish`.

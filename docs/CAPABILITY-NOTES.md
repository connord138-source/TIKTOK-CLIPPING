# Capability notes — clipping pipeline feasibility

## Re-verified 2026-11-18 (GTA 6 build session)
Network policy has been partially opened since 2026-09-22:
| Host / capability | Result |
|---|---|
| youtube.com search + metadata + json3 auto-captions | **works** (word-level timings) — but bot-checks the datacenter IP after ~10 rapid metadata calls |
| *.googlevideo.com (YouTube media) | **blocked** (000) → no YouTube rendering from cloud sessions |
| twitch.tv channel clips listing via yt-dlp | **works** (title, views, duration, timestamp) |
| twitch.tv category clips via yt-dlp | unsupported by yt-dlp → Helix API path (needs TWITCH_CLIENT_ID/SECRET) |
| tiktok.com public profile via yt-dlp | **works**: per-video views/likes/comments/shares (no follower count) |
| kick.com, huggingface.co, pypi | reachable |
| ffmpeg render chain | **validated** again: 27s clip, both layouts, ~20s each, QC passes |

### Higgsfield → TikTok drafts (tested 2026-11-18 from the cloud session)
| Step | Result |
|---|---|
| `tiktok_accounts` | one account, `active`, connected 2026-09-26 |
| `media_upload` + curl PUT to `upload.higgsfield.ai` | **HTTP 200** (7 MB, 27 s test clip) |
| `media_confirm` | `uploaded`, returns a Higgsfield CloudFront URL |
| `tiktok_prepare_publish` (`UPLOAD_TO_DRAFT`) | returns a publish session + a **form the user must submit**; Claude cannot submit it, and clients without MCP Apps widgets cannot publish |
| Form submit → draft appears in TikTok | not yet confirmed by the user |
| Does the caption carry into the TikTok draft? | unknown; the user may need to paste it in TikTok |

So drafts cannot be sent by the Python farm or by autopilot: each one needs a Claude session
that can read the clip file, plus one form submit from the user.

### Dashboard one-click drafts via TikTok's own API (built 2026-11-18)
Implemented from TikTok's docs: desktop Login Kit with PKCE (hex SHA-256 challenge),
`/v2/post/publish/inbox/video/init/` + chunked PUT, `/v2/post/publish/status/fetch/`.
| Check | Result |
|---|---|
| Automated tests against a local stand-in for the API | pass (login, single and chunked upload, errors, posted sync) |
| Real TikTok init endpoint with a bad token | answers `access_token_invalid` in the expected shape |
| Real login + real upload with the user's TikTok app | **not tested** (needs the user's app) |
| TikTok portal accepts `http://127.0.0.1:8787/...` as a Desktop redirect URI | **no** (2026-11-18: "localhost is not supported", despite the docs). Workaround: Web platform + the https forwarding page `docs/tiktok-callback/` on GitHub Pages, set in Connections as the redirect address |
| Does a sandbox (unreviewed) app get `video.upload` for inbox uploads? | **unknown**: docs say the app "must be approved for the video.upload scope" and don't say whether sandbox target users are exempt |

Conclusion: cloud sessions can scout, plan, analyse and run agents; **rendering YouTube sources
needs the user's machine** (or a policy that allows `*.googlevideo.com` — wildcard hosts are a
Settings decision, not something a session can add).

---
## Original findings (2026-09-22)

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

## Ingest: BLOCKED by current environment network policy
Connectivity matrix (via agent proxy; 000 = CONNECT denied by policy):
| Host | Result |
|---|---|
| raw.githubusercontent.com | **206 (works, range requests OK)** |
| youtube.com / twitch.tv / kick.com | 000 blocked |
| drive.google.com | 000 blocked |
| whop.com / contentrewards.com | 000 blocked |
| huggingface.co (whisper models) | 000 blocked |
| cdn.higgsfield.ai (!) | 000 blocked — can't download Higgsfield outputs locally either |

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

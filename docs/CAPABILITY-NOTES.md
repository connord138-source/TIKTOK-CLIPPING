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

**Fix (user action):** claude.ai/code → environment settings → network access. Either
full access, or allowlist at minimum: `youtube.com, *.googlevideo.com, twitch.tv,
*.ttvnw.net, kick.com, drive.google.com, *.googleusercontent.com, whop.com,
contentrewards.com, huggingface.co, *.hf.co, cdn.higgsfield.ai`.
Docs: https://code.claude.com/docs/en/claude-code-on-the-web

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

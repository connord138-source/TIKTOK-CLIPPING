# Ledger

`videos.json` — one entry per clip (or video), from planned to verified payout. Managed
via `scripts/ledger.py` (add / set / list / report). Append-only in spirit: never delete
entries; kill with `status: "killed"` so the record survives.

## Entry schema — clipping model
| Field | Type | Notes |
|---|---|---|
| `id` | str | `v001`, `v002`, … (auto-assigned) |
| `title` | str | working title of the clip |
| `status` | str | `planned → clipped → posted → verified → paid` (or `killed`, `rejected`) |
| `campaign` | str | campaign id/name (Whop etc.) — REQUIRED before posting |
| `rate_per_1k` | num | campaign USD per 1k verified views |
| `source_url` | str | VOD the clip came from |
| `vod_window` | str | timestamps in the source VOD, e.g. `1:10:40-1:11:06` |
| `clip_file` | str | `work/<job>/clip-NNN.mp4` (media is gitignored; path is the record) |
| `hook` | str | burned-in hook text |
| `posted_at` | str | ISO date |
| `tiktok_url` | str | once posted |
| `views` / `likes` / `comments` / `shares` / `saves` | num | platform metrics |
| `verified_views` | num | views the campaign actually credits |
| `earnings_usd` | num | recorded payout (estimated from rate×views until set) |
| `payout_status` | str | `pending → verified → paid` (or `rejected`) |
| `credits_spent` | num | actual Higgsfield credits, when AI steps are used |
| `idea_id` | str | legacy backlog reference (POV-history era) |
| `created_at` / `updated_at` | str | auto |

`report` aggregates per campaign: clips, views, earned (estimated until `earnings_usd`
lands) and paid out. Any extra `key=value` passed to `ledger.py set` is stored as-is —
the schema is a floor, not a ceiling.

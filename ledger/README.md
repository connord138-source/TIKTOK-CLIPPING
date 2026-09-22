# Ledger

`videos.json` — one entry per video, from idea to posted metrics. Managed via
`scripts/ledger.py` (add / set / list / report). Append-only in spirit: never delete
entries; kill with `status: "killed"` so the cost data survives.

## Entry schema
| Field | Type | Notes |
|---|---|---|
| `id` | str | `v001`, `v002`, … (auto-assigned) |
| `idea_id` | str | backlog reference, e.g. `idea-003` |
| `title` | str | working title |
| `status` | str | `planned → scripting → generating → review → draft_ready → posted` (or `killed`) |
| `script` | str | VO script |
| `shot_plan` | str | segments + model + params used |
| `model` | str | e.g. `seedance_2_5` |
| `job_ids` | str | comma-joined Higgsfield job ids |
| `credits_spent` | num | **actual** total credits, from job receipts |
| `virality_score` | num | from `virality_predictor` |
| `publish_id` | str | from `tiktok_prepare_publish` |
| `tiktok_url` | str | once posted |
| `posted_at` | str | ISO date |
| `views` / `likes` / `comments` / `shares` / `saves` | num | metrics sessions update these |
| `created_at` / `updated_at` | str | auto |

Any extra `key=value` passed to `ledger.py set` is stored as-is — the schema is a
floor, not a ceiling.

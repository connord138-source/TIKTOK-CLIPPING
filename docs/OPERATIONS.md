# Operations Runbook

How a Claude session runs this business. Two session types. Every session ends with
ledger updated, committed, pushed.

## A. Production session (default)

1. **Load state:** `config/account.json`, `content/backlog.json`,
   `python3 scripts/ledger.py report`.
2. **Budget check:** `mcp__HIGGSFIELD__balance`. Abort generation if a batch would take
   balance below `budget.balance_floor_credits` (150). Session spend cap: 250 credits
   unless the user raises it in-session.
3. **Pick 2–3 ideas** from backlog by `priority` (highest first). Mark `status: "scripting"`.
4. **Script each video** (goes into the ledger entry, not a separate file):
   - VO script: ~150–170 words for 60–75s, written for the ear, hook line first.
   - Shot plan: 2–3 segments × 20–25s (Seedance 2.5 supports 4–30s per gen with audio).
   - Text overlays: hook question + captions.
5. **Generate:** prefer one of:
   - `generate_video` model `seedance_2_5`, `aspect_ratio: "9:16"`, `resolution: "720p"`,
     `generate_audio: true`, duration 20–25s per segment; batch segments via
     `generate_video_batch` → `jobs_wait` → one `show_generation_by_ids`.
   - `shorts_studio_create` when the concept fits a full automated short (check
     `get_workflow_instructions` first per MCP guidance for multi-step videos).
   - VO layer: `generate_audio` if model-native audio isn't good enough; pick a
     consistent narrator voice once and reuse (`list_voices`).
6. **Quality gate, every video:**
   - Manual review of every output (watch it via `job_display`).
   - `virality_predictor` — record its score in the ledger. Weak concept → one retry
     max (`budget.max_retries_per_idea`), else mark `status: "killed"` and move on.
7. **Prepare draft (never direct-post):** once TikTok is connected,
   `tiktok_prepare_publish` in draft/inbox mode with caption from
   `config.style.caption_template`, AI-generated label ON. Record the publish id.
8. **Ledger + push:** for each video `scripts/ledger.py add/set` with: script, shot plan,
   model + params, **actual credits_spent per job**, virality score, status
   (`draft_ready` / `killed`), publish id. Update the cost table below when real numbers
   land. Commit and push.

## B. Metrics session (run ~24–48h after posts go live, and weekly)

1. `tiktok_publish_status` / account analytics for each posted video → `scripts/ledger.py set
   <id> views=… likes=… comments=… shares=… saves=…`.
2. `python3 scripts/ledger.py report` → cost per 1k views per format.
3. **Iterate:** top ~20% formats get 2× representation in the next backlog refill;
   bottom formats die. Mine comments for Part 2 requests → new backlog entries with
   `source: "comments"`.
4. Refill backlog to ≥10 ideas. Commit and push.

## Cost table (calibrate with real receipts — TBD until batch 1)

| Item | Config | Credits (actual) |
|---|---|---|
| Seedance 2.5 segment | 9:16, 720p, ~22s, audio on | TBD |
| FLUX 3 Video segment | 9:16, 720p, ~15s, audio on | TBD |
| Shorts Studio short | preset TBD | TBD |
| generate_audio VO | ~70s | TBD |
| Full finished video (all-in) | 60–75s | TBD |

Balance snapshot 2026-09-22: **461 credits** (Plus plan). Until the table is calibrated,
assume a finished video costs 60–120 credits → first batch = 2–3 videos max.

## Standing decisions
- Draft-only publishing until the user flips `publish_mode` — the human taps post.
- One niche, one account (see STRATEGY.md).
- Scheduled/recurring production (a Routine that wakes Claude daily) is built-ready but
  OFF until the user opts in — it spends credits unattended.
- Stitching note: if multi-segment assembly is needed and Shorts Studio doesn't cover it,
  TikTok's own editor can sequence draft clips at post time; keep segments self-contained
  so hard cuts read as intentional. Revisit a proper assembly step (ffmpeg or
  `sandbox_exec`) only if this shows in retention data.

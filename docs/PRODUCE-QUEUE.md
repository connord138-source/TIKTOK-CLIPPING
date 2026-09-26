# PRODUCE-QUEUE — the pick→produce loop (agent runbook)

The user picks campaigns on the ops board (artifact) and taps **Queue a clip**. That
writes a doc into the board's database. This runbook turns a queued doc into a finished
clip + posting package **back on the board**. A Routine fires a fresh session hourly
(9am–11pm ET) to run this; the 2x-daily guard sessions keep the pools/board fresh.

**Board artifact:** `https://claude.ai/artifact/EtDiVJQckfXQHTAoySKpoj`
(also in `config/dashboard.json`). DB + assets via the `ArtifactData` / `Artifact`
tools (ToolSearch: `select:ArtifactData`).

## Hard boundaries (CLAUDE.md rules apply in full)
- **Never post or publish anywhere.** The deliverable is a video + package ON THE BOARD.
  The user posts from the phone app and clicks Submit clip themselves.
- **Campaign-authorized material only.** Source must come from the campaign's own
  sources (config/campaigns.json) or the board's cached source assets.
- **Check the pool before producing** (the CoD lesson). Pool ≤ $50 → kill the item.
- Max **2 queue items per run**, oldest first. Budget rules apply if Higgsfield is used
  (default: it is not — clipping burns no credits).

## 0 · Triage (BEFORE any installs — costs ~30s)
1. `ArtifactData query` collection `queue`, where `status == "queued"` (orderBy `created` asc).
2. Also query `status == "producing"`: any doc with `updated` older than 4h is a dead
   session's stale claim → `update` it back to `status:"queued"` (append note) and treat normally.
3. **Nothing to do → end the session immediately and silently.** No summary, no notification.

## 1 · Claim
`update` the doc: `{status:"producing", claimed_by:"agent <date>", updated:<now_ms>}`
pinned with `if_version` from your read. Pin fails → someone else claimed it; re-read and skip.

## 2 · Verify the pool
`python3 scripts/whop_scout.py detail <cr_campaign_id>` (ids in config/campaigns.json).
- ≤ $50 left → doc `{status:"killed", kill_reason:"pool dead ($X left)"}`; flip the
  campaign's db doc to `flag:"dead"`, `can_queue:false`; update config/campaigns.json; skip item.
- Also refresh `rem` in the campaign's db doc while you're here.

## 3 · Bootstrap + sources
Bootstrap only once a real item exists: `pip install yt-dlp faster-whisper` and ffmpeg via
apt if missing → `python3 scripts/clipper.py doctor` (see OPERATIONS.md §bootstrap).

Fresh containers have NO `work/` files. Source priority for **coinbase-valorant-oneshot**:
1. **Board asset cache** — download via `Artifact` read with `path:<asset id>`:
   - `aecee81453245f19f99163f096a477f6` 1v1-mezz.mp4 (the insane 1v1, 17MB source re-enc)
   - `3cf63dae8df05965c65eb7035f4d7a19` sub-drop-mogi-mezz.mp4 (sub-drop pop-off — UNUSED yet)
   - `8eeb1a1471a1c64fb06d5fc6cdcb7ffe` wait-sliggy-no.mp4 (caster disbelief — UNUSED yet)
   - `6d99a2199432602f61ea7187bd526aa4` tenz-break.mp4 (TenZ setup break — UNUSED yet)
   - `0b951fee473fc8e11e62383a00814856` might-as-well-play.mp4 (banter beat — UNUSED yet)
   - `d606e0f5824413c029856ee19f989838` guidelines.pdf (campaign rules)
2. **Full VODs** (deeper mining): TenZ NA/EU, Sliggy, Mixwell VODs are in the campaign
   Dropbox (link in config/campaigns.json; per-file `?rlkey=…&dl=1` works, folder zip
   doesn't — listing needs Higgsfield `sandbox_exec`, see docs/CAPABILITY-NOTES.md).
   Twitch VODs ingest directly via `clipper.py ingest --section` (validated lane).
Already-shipped edits (do NOT redo): the 1v1 (`q-val-1v1-v9`), tenz-replay, tenz-clutch.

## 4 · Produce — v9 template (locked; account.json §style)
**Intro = the actual impact moment + win/payoff banner held ~2s (punched in 1.12, hook
text on the seam) → then the ENTIRE clip from the top.** Never open on setup; the
reaction lives in the full playthrough, never in the intro.

Reference invocation (the shipped 1v1):
```
python3 scripts/clipper.py stitch --job <job> --segments "11.7-15.8,2.0-20.3" \
  --zooms "1.12,1" --hook "THIS SHOT BROKE TENZ" --layout stack \
  --cam 0,0,456,312 --game 528,0,864,944
```
- `--segments "<impact window>,<full clip>"` — impact window ~2–4s ending just past the
  banner/payoff; full clip from the top including the reaction.
- `--layout stack`: facecam crop top (~740px of 1920), gameplay crop bottom. Find crops
  with `probe` + a frame grab; `--cam/--game x,y,w,h` are source-pixel crops.
- Hook: ≤6 words, caps, payoff-flavored, campaign-compliant (Valorant: prize wording
  ONLY as "a shot at 1 BTC"; no FOMO/financial-advice phrasing, no "anyone can enter").
- Captions on (word-accent cards) unless the campaign forbids burned text; loudnorm on.
- QC: `clipper.py qc` + watch first/last 2s. One regeneration max on a weak result.

## 5 · Deliver to the board
1. `qc` passed → upload the finished mp4 as a board asset (`Artifact` publish,
   `asset:true`, `url` = board). **≤14.5MB.** Bigger → re-encode delivery copy
   (`-crf 22/23`) until it fits; if still no, skip the asset and say so in `clip.delivery`.
2. ALSO send the full-quality file with SendUserFile (belt and braces — asset link + file card).
3. Build the package from the campaign's `post_recipe` (config/campaigns.json):
   caption (disclosure + required tag + approved copy + 2-3 topic hashtags), window
   (tonight/tomorrow, 2/day ≥4h apart, 6–10pm ET prime), ai_label (OFF unless an AI
   element was added), audio note, submit_url, checklist (follows/geo-tag/label/submit steps).
4. `update` the queue doc (pin `if_version`):
   `{status:"ready", updated:<now_ms>, clip:{name,length_s,asset_url:"/_blob/<id>",delivery},
   package:{caption,window,ai_label,audio,submit_url,checklist:[…]}}`
5. Refresh `meta/board`: stamp + do_next entry pointing at the READY card.

## 6 · Close the loop
- `scripts/ledger.py add` (status `produced`, campaign, params used, `credits_spent` if any).
- Update configs if campaign state changed. **Commit + push** (ledger/config/docs only;
  media stays out of git).
- End with a 2-line summary naming the clip + campaign (this reaches the user's push
  notification): e.g. `READY: sub-drop pop-off (Valorant) — video + package on the board.`

## Statuses (the page renders these)
`queued` → user picked · `producing` → claimed (heartbeat: bump `updated` between long
steps) · `ready` → video + package on the board · `posted` → user marked it (post_url set;
guard sessions mirror it into posts/ + ledger) · `killed` → cancelled or dead pool
(`kill_reason`). Board DB is capped at 5k docs — archive `posted`/`killed` docs older
than 14 days into the ledger, then delete them.

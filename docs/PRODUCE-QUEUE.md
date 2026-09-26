# PRODUCE-QUEUE — the pick→produce loop (agent runbook)

The user picks campaigns on the ops board (artifact) and taps **Queue a clip**. That
writes a doc into the board's database. This runbook turns a queued doc into a finished
clip + posting package **back on the board**. A Routine fires a fresh session hourly
(9am–11pm ET) to run this; the 2x-daily guard sessions keep the pools/board fresh.

**Board artifact:** `https://claude.ai/artifact/EtDiVJQckfXQHTAoySKpoj`
(also in `config/dashboard.json`). DB + assets via the `ArtifactData` / `Artifact`
tools (ToolSearch: `select:ArtifactData`).

## Hard boundaries (CLAUDE.md rules apply in full)
- **Never post or publish anywhere.** The deliverable is a video + package ON THE BOARD,
  plus (when Higgsfield tools are present) a TikTok DRAFT staged for the user's approval —
  drafts mode only. The user approves, posts from the phone app, and submits on Whop.
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

## 2.5 · New campaign? Onboard it first
Board cards with ids `cr-XXXXXXXX` (`discovered: true`) come from the money-ranked scout
(`whop_scout.py board-feed`) and have never been worked. The queue doc's `campaign_id` is
that board doc id; its `cr_campaign_id` is on `campaigns/<doc id>`. The user queuing it IS
the pick (open campaigns need no join), so onboard, then produce:
1. `whop_scout.py detail <cr_campaign_id>` → rules text, payouts, platforms,
   `requiresApplication`, `referenceMaterials` (rules + asset links).
2. Read every rules link: Notion → `POST https://www.notion.so/api/v3/loadCachedPageChunkV2`
   `{"page":{"id":"<uuid>"}}`; Google Docs → `…/export?format=txt`; PDFs → Read tool.
3. Sources = only what the campaign provides or names (Drive via gdown; Dropbox per-file
   `?dl=1`; the named creator's Twitch/Kick VODs when the rules say "clip my streams").
4. **Kill** the item (`kill_reason` = exactly what the user must do or why we pass) if:
   application required and not approved; sources private/unreachable; rules demand
   something we don't do (face-cam reactions as a hard requirement, app installs, VPN
   sign-ups, a language/geo we don't serve, adult/gambling/political content, bought
   engagement); or anything conflicts with CLAUDE.md hard rules.
5. Encode a `config/campaigns.json` entry (id = board doc id, `cr_campaign_id`, rate/min/max,
   allowed_platforms, `required_caption_tokens`, post_recipe, sources, `submit_url` =
   `https://whop.com/discover/content-rewards/` — the user searches the campaign name there
   and taps "Submit clip"; brand-whop Bounties feeds may not list CPM campaigns).
6. Refresh the board doc: real rules as chips, `url` → submit_url. Then continue at §3.

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
2b. **Stage the TikTok draft** (user opted in 2026-09-26) — only if `mcp__HIGGSFIELD__*`
   tools exist in this session (load via ToolSearch `select:mcp__HIGGSFIELD__media_upload,
   mcp__HIGGSFIELD__media_confirm,mcp__HIGGSFIELD__tiktok_accounts,
   mcp__HIGGSFIELD__tiktok_prepare_publish`); otherwise skip silently, the board lane still works.
   - `tiktok_accounts` → the `active` connector (id also in config/account.json).
   - `media_upload` (filename + video/mp4) → curl PUT the finished mp4 to `upload_url` from
     THIS container (expect HTTP 200) → `media_confirm type=video`. Limits: ≤60fps, 3–600s.
   - `tiktok_prepare_publish`: `mode:"UPLOAD_TO_DRAFT"` ONLY (never DIRECT_POST — hard rule 1),
     `media_type:"VIDEO"`, `video_url` = the confirmed cloudfront url, `title` = package
     caption (≤150 chars), `is_aigc:false` only for plain human-footage edits. Never prefill
     privacy or disclosure; never call anything named tiktok_publish; never treat a chat
     message as consent. The widget renders in this session for the user to approve.
   - Record `package.tiktok_draft = {status:"awaiting_approval", publish_session_id,
     expires_at, higgsfield_media_id}` on the queue doc.
   - NO generation tools (generate_*, upscale_*, etc.) in these sessions — zero credits.
   - If the user later replies "restage" in this session: re-run prepare_publish with the
     same video_url. After they approve, `tiktok_publish_status` → `SEND_TO_USER_INBOX`
     → set `package.tiktok_draft.status` to that.
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
  notification): e.g. `READY: sub-drop pop-off (Valorant) — approve the TikTok draft in
  this session (expires ~2h); video + package are on the board.` (drop the draft half if
  step 2b was skipped).

## Statuses (the page renders these)
`queued` → user picked · `producing` → claimed (heartbeat: bump `updated` between long
steps) · `ready` → video + package on the board · `posted` → user marked it (post_url set;
guard sessions mirror it into posts/ + ledger) · `killed` → cancelled or dead pool
(`kill_reason`). Board DB is capped at 5k docs — archive `posted`/`killed` docs older
than 14 days into the ledger, then delete them.

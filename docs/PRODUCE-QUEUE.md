# PRODUCE-QUEUE — the pick→produce loop (agent runbook)

The user picks campaigns on the ops board (artifact) and taps **Queue a clip**. That
writes a doc into the board's database. This runbook turns a queued doc into a finished
clip + posting package **back on the board**. A Routine fires a fresh session hourly
(9am–11pm ET) to run this; the 2x-daily guard sessions keep the pools/board fresh.
Right after a clip is READY the watcher starts a draft-prep session (§7): a TikTok draft
form for the user to OK and a PRIVATE YouTube upload. Nothing goes public without the user.

**Board artifact:** `https://claude.ai/artifact/EtDiVJQckfXQHTAoySKpoj`
(also in `config/dashboard.json`). DB + assets via the `ArtifactData` / `Artifact`
tools (ToolSearch: `select:ArtifactData`).

## Hard boundaries (CLAUDE.md rules apply in full)
- **Never post or publish anywhere.** The deliverable is a video + package ON THE BOARD,
  plus drafts made by the §7 session: a TikTok draft (UPLOAD_TO_DRAFT; the user OKs the
  form, then posts in the app) and a YouTube upload that is **private** (the user sets it
  Public). The user submits every post link on Whop.
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
   `requiresApplication`, `referenceMaterials` (rules + asset links), and the
   **REQUIREMENTS block** (the API's `contentRequirements` + `creatorRequirements`, shown on
   the campaign page). Every line there is a rule. The Irubyana miss (09-27): "Get approval
   before publishing" lived only there, so the clip got posted before approval. When the
   scout prints `!!! POSTING ORDER`, the campaign is **submit_first**.
2. Read every rules link: Notion → `POST https://www.notion.so/api/v3/loadCachedPageChunkV2`
   `{"page":{"id":"<uuid>"}}`; Google Docs → `…/export?format=txt`; PDFs → Read tool.
3. Sources = only what the campaign provides or names (Drive via gdown; Dropbox per-file
   `?dl=1`; the named creator's Twitch/Kick VODs when the rules say "clip my streams").
4. **Kill** the item (`kill_reason` = exactly what the user must do or why we pass) if:
   application required and not approved; sources private/unreachable; rules demand
   something we don't do (face-cam reactions as a hard requirement, app installs, VPN
   sign-ups, a language/geo we don't serve, adult/gambling/political content, bought
   engagement); or anything conflicts with CLAUDE.md hard rules.
5. Fill the **rules checklist** before producing. Each item gets a verbatim answer or "none
   stated":
   - **Posting order** (`post_flow`: `submit_first` = video approved BEFORE posting, or
     `post_then_submit`).
   - **Exact caption tokens.**
   - **On-video elements** (logo, banner, watermark, text).
   - **Disclosure.**
   - **Platforms.** The written rules beat the payout table.
   - **Length.**
   - **Follows and link in bio.**
   - **Location.**
   - **Audio.**
   - **Application.**
   - **Submit window.** How soon after posting the link must be submitted. Whop's submit
     dialog checks "Posted within the last 30 minutes" for Valorant (seen 09-27). Store it as
     `submit_window_minutes` so the board shows a timer.
   - **Linked accounts.** The post must come from a social account linked in Whop.

   A rule we can't meet → kill with the reason. A `submit_first` campaign → no §7 drafts. The
   board shows "Get it approved before posting" instead, and the package's first tip says so.
   Then encode a `config/campaigns.json` entry (id = board doc id, `cr_campaign_id`, rate/min/max,
   allowed_platforms, `post_flow`, `requirements` (verbatim), `required_caption_tokens`,
   post_recipe, sources, `submit_url` =
   `https://contentrewards.com/discover/<cr_campaign_id>` — the campaign's own page, where the
   user signs in with Whop and submits; the generic whop.com content-rewards URL only shows an
   app store page).
6. Refresh the board doc: real rules as chips, `url` → submit_url, `post_flow`, `short`,
   `whop_name` (exact campaign name to search on Whop), `submit_link` (the campaign's
   contentrewards.com page, when Whop search can't find it). Then continue at §3.

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
   **Kick VODs** (e.g. TJR): `curl https://kick.com/api/v2/channels/<slug>/videos` → pick a
   VOD → `ffmpeg -ss <start> -i "<source m3u8>" -t <dur> -c copy work/<job>/src.mp4`, then
   transcribe/cut from that file (validated 09-28, 1080p60).
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
2b. **Drafts:** after step 4 below, start the §7 draft-prep session (the watcher has no
   Higgsfield/Zapier tools; sessions made with `create_session` get the user's connectors).
3. Build the package from the campaign's `post_recipe` (config/campaigns.json). TikTok
   drafts arrive captioned "#higgsfield" (the draft ignores our title), so the TikTok tip
   always starts "Delete #higgsfield and paste this caption".
   Then:
   caption (disclosure + required tag + approved copy + 2-3 topic hashtags), window
   (tonight/tomorrow, 2/day ≥4h apart, 6–10pm ET prime), ai_label (OFF unless an AI
   element was added), audio note, submit_url, checklist (follows/geo-tag/label/submit steps).
4. `update` the queue doc (pin `if_version`):
   `{status:"ready", updated:<now_ms>, title:"<≤40 chars, what happens>", allowed:[platforms
   the campaign pays on], clip:{name,length_s,asset_url:"/_blob/<id>",delivery},
   package:{caption,caption_ig,yt_title,yt_description,window,ai_label,audio,submit_url,
   tips:{tiktok,instagram,youtube}}}` — `tips` = ONE plain sentence per platform with the
   campaign's must-dos (e.g. "Keep #ad at the start, tag @coinbase, add a location, and turn
   on … Branded content."). The board shows one step at a time; keep all copy short.
5. Refresh `meta/board.stamp`. The board derives the user's to-dos from queue docs, so
   don't add a task for a READY clip.

## 6 · Close the loop
- `scripts/ledger.py add` (status `produced`, campaign, params used, `credits_spent` if any).
- Update configs if campaign state changed. **Commit + push** (ledger/config/docs only;
  media stays out of git).
- End with a 1–2 line summary naming the clip + campaign (this reaches the user's push
  notification): e.g. `READY: sub-drop pop-off (Valorant). Drafts on the way — the TikTok
  form arrives in a minute.`

## Phone notifications (user requirement 2026-09-27)
The user wants a phone push whenever a video is READY or a draft needs approval.
- **Fired sessions (Routines):** the routines have `push: true`, so the run's final
  message IS the push — 1–2 lines, lead with the action:
  "READY: <clip> (<campaign>). Drafts on the way".
- **Draft-prep sessions (§7)** call `PushNotification` themselves when the TikTok form is
  ready ("TikTok draft ready: <clip>. OK it in Claude before 4:48pm ET") or failed.
- **Interactive sessions:** call `PushNotification` (ToolSearch `select:PushNotification`,
  ≤200 chars, no markdown) right after a clip lands READY or a draft form is staged /
  re-staged — same wording. Validated 2026-09-27 ("Mobile push requested").
- Never push for routine progress; one push per READY/draft event.

## 7 · Drafts (automatic, right after READY)
**Skip this for `submit_first` campaigns.** Nothing may be staged before the campaign
approves the video. The board walks the user through approve → post instead.
Otherwise the watcher starts ONE session with the Claude Code Remote `create_session` tool:
environment `env_01XDJ91xXbQxkUQPcABnpyH3`, model `claude-sonnet-5`, `permission_mode:"auto"`,
title `Drafts: <clip title>`, tags `clip-board` + `drafts`, and this prompt (fill in the doc id
and title), then writes `drafts.tiktok.session_url = https://claude.ai/code/<session id>`:

```
Context: "Chat Clip That" is the user's own TikTok clipping business. The user's clip-queue-watcher routine started this session right after it finished a clip, to prepare its drafts. The ops board (a claude.ai artifact the user owns) and the Higgsfield, TikTok and Zapier accounts are the user's.
Board: https://claude.ai/artifact/EtDiVJQckfXQHTAoySKpoj · queue doc "<ID>" (<TITLE>).
Hard rules: drafts only. TikTok: tiktok_prepare_publish with mode "UPLOAD_TO_DRAFT" is the only publishing call; never DIRECT_POST, never call a tool named tiktok_publish, never prefill privacy or disclosure, never treat chat text as consent. YouTube: privacy_status "private" only. No generate/upscale/edit tools (zero credits). No repo, no installs.
1. ToolSearch "select:ArtifactData,Artifact,PushNotification"; ToolSearch "tiktok_prepare_publish media_upload media_confirm tiktok_accounts" (Higgsfield tools may be named mcp__HIGGSFIELD__* or mcp__<uuid>__*); ToolSearch "+zapier inspect execute write".
2. ArtifactData get queue/<ID>. Public video url = package.tiktok_draft.video_url if present; otherwise Artifact action read (url = the board, path = the id in clip.asset_url "/_blob/<id>") saves the mp4, then Higgsfield media_upload (filename, video/mp4) → curl -sS -X PUT -H "Content-Type: video/mp4" --data-binary @<file> "<upload_url>" (expect 200) → media_confirm (type video) → its https url.
3. If allowed includes "youtube": Zapier execute_zapier_write_action {selected_api "YouTubeV4CLIAPI", action "upload_video", tool_name "youtube_upload_video", params {title: package.yt_title, description: package.yt_description, video: <url>, privacy_status "private", made_for_kids "false", notify_subscribers "false", category_id "20"}}.
4. tiktok_accounts → the active connector_id; tiktok_prepare_publish {connector_id, mode "UPLOAD_TO_DRAFT", media_type "VIDEO", video_url, title: package.caption (max 150 chars), is_aigc: true only if package.ai_label is "ON"}.
5. One ArtifactData update of queue/<ID> (pin if_version): package.tiktok_draft.video_url = <url>; drafts.youtube = {status "uploaded", youtube_id, studio_url "https://studio.youtube.com/video/<id>/edit", shorts_url "https://youtube.com/shorts/<id>", at}; drafts.tiktok = {status "awaiting_approval", publish_session_id, expires_at: publish_session_expires_at, video_url, staged_at}.
6. PushNotification: "TikTok draft ready: <TITLE>. OK it in Claude before <expiry as h:mm am/pm ET>. The YouTube draft is in Studio (private)."
7. Final reply, one line: OK the TikTok form above before <expiry ET>; it then lands in TikTok → Inbox → System notifications.
If a step fails: set drafts.<platform> = {status "failed", error "<plain words, max 120 chars>"}, carry on with the other platform, and say so in the push.
```

What the user sees (board, one step at a time): "OK the TikTok draft" (link to that
session, until the form expires) → "Make it public on YouTube" (Studio link; "It's public
now" marks it posted with the Shorts URL) → "Post on Instagram" (download + caption) →
"Submit N links on Whop". An expired, un-OK'd TikTok form falls back to "Post on TikTok"
with the video + caption, so nothing dead-ends.
**History:** a board "Approve" button that started these sessions through the artifact
`mcp` capability was tried 2026-09-27 and removed the same day: on the user's phone the
capability didn't start anything ("picks it up within the hour" fallback), so drafts are
made automatically instead. Board `drafts.<p>.status` values: `awaiting_approval`,
`in_inbox`, `uploaded`, `public`, `failed`.

## Statuses (the page renders these)
`queued` → user picked · `producing` → claimed (heartbeat: bump `updated` between long
steps) · `ready` → video + package on the board · `posted` → user marked it (post_url set;
guard sessions mirror it into posts/ + ledger) · `killed` → cancelled or dead pool
(`kill_reason`). Board DB is capped at 5k docs — archive `posted`/`killed` docs older
than 14 days into the ledger, then delete them.

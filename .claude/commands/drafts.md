---
description: Send approved clips to the user's TikTok drafts through Higgsfield (the user submits each form and posts from TikTok).
---
Send approved clips to the user's **TikTok drafts** using the Higgsfield connector.

This is the fallback path. If the dashboard's Connections tab shows TikTok as "connected · can
send drafts", tell the user to use the **Send to TikTok drafts** button there instead.

Hard rules
- Mode is always `UPLOAD_TO_DRAFT`. Never `DIRECT_POST`. Never call `tiktok_publish` yourself:
  the user submits the publish form that `tiktok_prepare_publish` shows them.
- Only clips with status `approved`. Never approve clips yourself.
- Don't prefill privacy or comment/duet/stitch choices. The user picks those in the form.

Steps
1. Run `python -m clipfarm drafts`. It returns `to_send` (approved clips in slot order with
   `file`, `title`, `description`), `is_aigc`, `open_slots_today` and `in_tiktok_drafts`.
   - `to_send` empty: say there is nothing approved and stop.
   - Any `file_exists: false`: this session cannot see the clip files (they live in
     `media/clips/` on the user's computer). Stop and tell the user to run `/drafts` from a
     Claude session on that computer, opened on this folder.
2. Call the Higgsfield `tiktok_accounts` tool and take the `active` account's `connector_id`.
   None active: ask the user to connect or reconnect TikTok in Higgsfield, then stop.
3. Pick the clips: the ids or count in the arguments below, else the first
   `min(open_slots_today, 5)` of `to_send`.
4. For each clip, in order:
   a. `media_upload` with `filename: "<id>.mp4"`, `content_type: "video/mp4"`.
   b. PUT the file to the returned `upload_url` from the machine that has the file, and
      expect HTTP 200 (in PowerShell use `curl.exe`, not `curl`):
      `curl -sS -o /dev/null -w "%{http_code}" -X PUT -H "Content-Type: video/mp4" --data-binary "@<file>" "<upload_url>"`
   c. `media_confirm` with `type: "video"` and the `media_id`. Keep the returned `url`.
   d. `tiktok_prepare_publish` with `connector_id`, `mode: "UPLOAD_TO_DRAFT"`,
      `media_type: "VIDEO"`, `video_url` (the Higgsfield url), `title`, `description`, and
      `is_aigc` from step 1.
5. Tell the user which form is which clip (id, hook, slot time) and ask them to submit each
   form. Sessions expire after about two hours.
6. When a form comes back with a `publish_id`, or the user says they submitted it, run
   `python -m clipfarm set-clip <id> drafted --publish-id <publish_id> --session <publish_session_id>`
   (leave out `--publish-id` if you never saw one). Leave unsubmitted clips as `approved`.
7. For each `publish_id`, call `tiktok_publish_status` once and report it.
8. Finish with a short table: clip, slot, state. Remind the user to open TikTok, find the
   draft, paste the caption if it didn't carry over (it's in the dashboard: Copy caption),
   post at the slot time, then click **Posted** in the dashboard.
9. Commit `data/clips.json` and push.

Verified limits (2026-11-18): the video must be Higgsfield-hosted (hence `media_upload`), MP4,
at most 1 GB, 3-600 s, at least 360 px per side, 23-60 fps. Farm output (1080x1920, 30 fps)
complies.

$ARGUMENTS

---
description: Run a full GTA 6 clip-farm session — scout, produce, analyse, commit.
---
Run today's clip-farm session for this repo (GTA 6 TikTok clips). Follow docs/OPERATIONS.md.

1. `python -m clipfarm doctor` (if yt-dlp is missing, run `pip install -q -r requirements.txt` first)
   and `python -m clipfarm status`. Summarise the plan in 3 lines.
2. Use the **gta-scout** agent, then the **clip-editor** agent (sequentially — the editor needs
   the scout's candidates). Run the **growth-analyst** agent in parallel with the editor if any
   clip was posted ≥24h ago.
3. Give me: today's slot board (time → clip id/hook), clips awaiting my review, sources that need
   my rights decision (top 5 by score with creator), and any campaign worth joining.
4. If approved clips exist and their files are visible here (`python -m clipfarm drafts` shows
   `file_exists: true`), offer to run `/drafts` to send them to my TikTok drafts.
5. Commit data/, config/ and docs/ changes and push to the working branch.

$ARGUMENTS

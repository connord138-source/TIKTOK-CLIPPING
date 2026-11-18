# Setup — run the GTA 6 clip farm on your machine

## 1. Install (once)
Needs Python 3.10+, ffmpeg, and a JS runtime for YouTube extraction (deno recommended, node works).

macOS:
```bash
brew install python ffmpeg deno
```
Windows (PowerShell):
```bash
winget install Python.Python.3.12 Gyan.FFmpeg DenoLand.Deno
```
Then in the repo:
```bash
python -m venv .venv
```
```bash
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```
```bash
pip install -r requirements.txt
```
```bash
python -m clipfarm doctor
```

## 2. Keys (all optional — the farm runs without them)
| What | Env var(s) | Unlocks |
|---|---|---|
| Claude brain | `ANTHROPIC_API_KEY` (or `ant auth login`) | Claude picks moments, writes hooks/captions, generates trend queries. Without it, heuristics |
| Twitch Helix | `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` (free app at dev.twitch.tv) | Top GTA VI clips across **all** of Twitch, not just the watchlist |
| TikTok Display API | `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` (developers.tiktok.com app with Login Kit, scopes `user.info.basic,user.info.stats,video.list`) | Follower count + official stats. Without it, public-profile stats (views/likes/comments/shares) still work |
| TikTok redirect | `TIKTOK_REDIRECT_URI` (default `http://127.0.0.1:8787/auth/tiktok/callback`) | TikTok may require an https redirect, so use a tunnel (e.g. cloudflared) if it rejects localhost |
| Faster captions for Twitch | `pip install faster-whisper` | Word captions on Twitch clips / own footage |

Put them in your shell profile or a `.env` you `source` (`.env` is gitignored).

If YouTube says "Sign in to confirm you're not a bot", set
`"ingest": {"cookies_from_browser": "chrome"}` (or firefox/edge/safari) in `config/account.json`.

## 3. Run
```bash
python -m clipfarm serve
```
Open http://127.0.0.1:8787 → **Run cycle** for a first scout + produce, or flip **Autopilot** on.

## 4. Status of external accounts
- TikTok @chat.clip.that: exists, 7 pre-pivot posts (non-GTA, incl. `#ad` campaign posts).
- Whop / Content Rewards: user-gated. Join GTA 6 campaigns surfaced in Sources → Campaigns.
- Higgsfield: optional now (AI intros/upscales). TikTok draft upload via `tiktok_prepare_publish`
  still requires `tiktok_connect` (user OAuth) and a publicly reachable clip URL.

# START HERE: your exact steps

Do Part A once. Then Part B today. Then Part C every day.

---

## Part A: Set it up on your computer (one time, ~30 min)

The farm runs on **your** computer. Your home internet isn't blocked by YouTube the way cloud servers are.

### A1. Install the tools
**Mac**: open Terminal and run:
```bash
brew install python ffmpeg deno git
```
(No `brew`? Install it first from https://brew.sh.)

**Windows**: open PowerShell and run:
```bash
winget install Python.Python.3.12 Gyan.FFmpeg DenoLand.Deno Git.Git
```
Close and reopen PowerShell afterwards.

### A2. Download the code
```bash
git clone https://github.com/connord138-source/TIKTOK-CLIPPING.git
```
```bash
cd TIKTOK-CLIPPING
```
```bash
git checkout claude/dreamy-ride-e3erns
```

### A3. Install the Python parts
```bash
python -m venv .venv
```
Mac:
```bash
source .venv/bin/activate
```
Windows:
```bash
.venv\Scripts\activate
```
Then:
```bash
pip install -r requirements.txt
```

### A4. Give it a Claude API key (this is what picks the best moments and writes hooks)
1. Go to https://console.anthropic.com → **API Keys** → **Create Key**. Copy it (starts `sk-ant-`).
2. Add a few dollars of credit under **Billing**. Expect about $0.01–0.03 per source video.
3. Save the key on your computer:

Mac (replace the key):
```bash
echo 'export ANTHROPIC_API_KEY=sk-ant-PASTE-YOURS' >> ~/.zshrc && source ~/.zshrc
```
Windows (replace the key, then close and reopen PowerShell):
```bash
setx ANTHROPIC_API_KEY "sk-ant-PASTE-YOURS"
```

Easier: skip this command, start the dashboard (A6), open the **Connections** tab, paste the
key under **Claude API key**, and click **Save**.

### A5. Check everything is installed
```bash
python -m clipfarm doctor
```
You want `OK` on ffmpeg, ffprobe, yt-dlp, js runtime, and claude brain. `WARN whisper` is fine.

### A6. Start the dashboard
```bash
python -m clipfarm serve
```
Open **http://127.0.0.1:8787** in your browser. Keep this terminal window open: closing it stops the farm.

Next time, you only need: `cd TIKTOK-CLIPPING` → activate (A3) → `python -m clipfarm serve`.

---

## Part B: Your first day

### B1. Get footage you're allowed to clip (the most important step)
The farm only auto-clips creators you have permission for. Pick at least one of these:

- **Join a paid GTA 6 clipping campaign** (this is also how you get paid):
  1. Go to https://contentrewards.com (Whop's Content Rewards) and search **GTA**.
  2. Join one or two campaigns. Note the **rate per 1k views**, the **max per clip**, and the **rules**.
  3. In the dashboard → **Sources** → **Add campaign**: type an id, name, rate, and max → Save.
  4. If the campaign is for a streamer: **Sources** → **Add creator** → their Twitch/YouTube name →
     rights = **campaign** → Add. Then pick that campaign in their row.
  5. If the campaign gives you source video links: **Scout** tab → **Clip a specific URL** → paste
     the link → rights = **campaign** → choose the campaign → **Clip it**.
- **Use your own GTA 6 gameplay** (if you play it): record clips on your console, copy the file to
  your computer, then **Scout** → **Clip a specific URL** → paste the **full file path**
  (e.g. `/Users/you/Movies/gta.mp4`) → rights = **own** → **Clip it**.
- **A creator says yes**: if a streamer has an open clipping program or tells you it's OK, find
  any of their videos in the **Scout** tab and click **Trust channel**. All their uploads now
  auto-clip.

### B1b. Or paste links you found yourself
You can skip the scout and feed the farm directly:
1. Find a popular GTA 6 video on YouTube (or a Twitch clip) and copy its link.
2. Dashboard → **Scout** tab → **Clip a link you found** → paste the link.
3. Leave start/end blank (the farm picks the best 1–2 moments), or type the seconds if you
   already know the moment.
4. Set the rights dropdown honestly: **campaign** / **permission** / **my own footage** if one
   applies, otherwise leave **no permission yet (my call)**.
5. Click **Clip it**. The clips appear in **Review** a few minutes later.

A pasted link is always clipped, whatever the label: that decision is yours per link. Clips
from creators with no program carry the copyright-strike risk described in `docs/STRATEGY.md`.

### B2. Find and make clips
1. Click **Run cycle** (top right). It searches YouTube and Twitch, then makes clips.
2. Watch progress in **Autopilot & activity**. A run takes about 2–10 minutes.
3. Check **Scout → Needs your call**. These are popular GTA 6 videos from creators you don't have
   permission for yet. Use them to decide which creators' campaigns to join (repeat B1).

### B3. Review
Go to the **Review** tab. For each clip:
- Watch it.
- Good: click **Approve**.
- Weak or broken: click **Reject**.
- Good moment but weak text: edit the hook → **Re-render** → then Approve.

Aim to approve 5 a day.

### B4. Post (you always post; the farm never does)
1. **Today** tab → find a slot marked **assigned** (times are US Eastern).
2. Click **Download**. Send the video to your phone (AirDrop, Google Drive, email), or use
   TikTok Studio on desktop.
3. Click **Copy caption**.
4. In TikTok: upload the video → paste the caption. Leave the **AI-generated label off**: it's
   real gameplay. If you're in a campaign, follow its rules (some require a sound or tag) → Post.
5. Back in the dashboard: click **Posted** and paste the TikTok video link.
6. If you're in a campaign, submit the TikTok link on the campaign page so you get paid.

### B4a. One-time: connect TikTok so the dashboard can send clips to your drafts
TikTok only lets an app you register upload to your account, so this needs a free TikTok
developer app. The labels on TikTok's site may differ slightly from these.
1. Go to https://developers.tiktok.com, log in with your TikTok account, open **Manage apps**,
   and create an app (any name, category Entertainment or similar).
2. In the app, add two products: **Login Kit** and **Content Posting API**.
3. In **Login Kit**, choose the **Desktop** platform and add the redirect URI shown in the
   dashboard's **Connections** tab (click **Copy** there). It is normally
   `http://127.0.0.1:8787/auth/tiktok/callback/`.
4. Make sure the scopes `user.info.basic` and `video.upload` are enabled.
5. Open the app's **Sandbox** settings, create a sandbox, and add your TikTok account as a
   **target user**. Use the sandbox's client key and secret.
6. In the dashboard → **Connections** → paste the **client key** and **client secret** → **Save**.
7. Click **Connect TikTok**, log in, and approve. The card should say
   **connected · can send drafts**.

If TikTok refuses uploads from a sandbox app, the clip shows "Not sent" with the reason. In
that case submit the app for review on TikTok's site, or keep using Download.

### B4a-2. Send clips to your TikTok drafts from the dashboard
1. **Today** tab → click **Send to TikTok drafts** on a slot, or **Send all ready clips**.
2. Wait for the slot to say **in TikTok drafts** (usually under a minute).
3. On your phone, open TikTok and tap the inbox notification. Paste the caption (TikTok's
   draft upload doesn't carry captions; use **Copy caption** in the dashboard), then post.
4. The dashboard marks the clip **posted** by itself within about five minutes.

TikTok allows 5 unposted drafts per 24 hours, so post or delete drafts before sending more.

### B4a-3. Captions on your phone
TikTok drafts arrive without a caption. To get it onto your phone in one tap:
1. Dashboard → **Connections** → **Captions on your phone** → switch on
   **Let my phone open the captions page**.
2. With your phone on the same Wi-Fi as the PC, point the phone's camera at the QR code and
   tap the link.
3. Add that page to your home screen.
4. Each day: open the page, tap **Copy caption**, switch to TikTok, open the draft, paste, post.

If the page won't load on the phone, Windows is blocking it: when the farm starts, Windows
asks whether to allow Python on your network, and it needs to be allowed for private networks.
Only the captions page is visible to the phone; the rest of the dashboard stays on the PC.

### B4b. Fallback: send drafts through Claude and Higgsfield instead
1. Install the **Claude desktop app** on this computer and sign in with the same account.
2. Open the **Code** tab and choose the folder `C:\Users\<you>\TIKTOK-CLIPPING`.
3. Type `/drafts` and press Enter.
4. Claude uploads your approved clips and shows a TikTok form for each one. Check the preview,
   pick your privacy and comment settings, and submit each form.
5. Open TikTok on your phone. The clips are in your drafts (TikTok also sends an inbox
   notification). Paste the caption if it's missing, then post at the slot time.
6. In the dashboard, click **Posted** on that slot.

### B4c. Or let it do everything: full auto
On the **Today** tab, the top box says **Do it all for me**. Click **Turn on full auto** and
confirm. From then on, with the PowerShell window left open, the farm:
1. looks for trending GTA 6 videos every 2 hours;
2. cuts clips from them (videos with no commentary are cut around the loudest action);
3. has Claude look at frames from each clip and approve or reject it;
4. sends approved clips to your TikTok drafts, up to 5 unposted at a time.

Your part is to open TikTok, tap the inbox notification, paste the caption and post.

What you agree to when you turn it on: it clips videos from any creator, including ones you
have no permission from (copyright complaints and strikes are your risk), and clips reach
your drafts without you watching them first. Each of the four switches can be turned off on
its own in **Autopilot & activity**.

### B4d. Automatic public posting with Upload-Post
TikTok won't let your own app post publicly, so public posting goes through Upload-Post, a
paid service (Basic plan, $24 a month, needed for TikTok).
1. Sign up at https://www.upload-post.com and choose the **Basic** plan.
2. In **User Management**, create a profile (for example `main`) and connect your TikTok,
   Instagram and YouTube accounts to it. One profile holds one account per platform.
3. In **API Keys**, click **Generate New API Key** and copy it.
4. In the dashboard → **Connections** → **Upload-Post** → paste the key → **Save**. Your
   profiles appear in a table.
5. Per profile, choose which platforms it posts to, its niches and posts a day (up to 15).
6. Test one clip by hand first: **Today** tab → **Post now** on a slot. It is published
   publicly with its caption.
7. When you're happy with the clips, switch on **Post automatically** for the profile.
   Approved clips are then scheduled at each slot time and published without you.

A scheduled clip can be taken back with **Cancel** on the Today tab until it goes live.

### B4e. Get an email when clips are ready
1. Turn on 2-Step Verification for your Google account if it isn't on already
   (https://myaccount.google.com/security).
2. Go to https://myaccount.google.com/apppasswords, create an app password named
   `Clip Farm`, and copy the 16 letters Google shows you.
3. Dashboard → **Connections** → **Email me when clips are ready** → type your Gmail
   address, paste the app password, click **Save**.
4. Click **Send test email** and check your inbox for "[Clip Farm] Test email".
5. Switch on **Send the email**.

After each run that makes clips you get one email whose subject starts with
`[Clip Farm] Clips ready`, listing how many clips, and each clip's niche and account.

### B5. Turn on Autopilot
Once you're happy with the clips, flip **Autopilot** on (top bar). It searches every 2 hours,
makes clips when the queue runs low, and pulls your TikTok stats every 6 hours. It still never posts.

---

## Part C: Every day (~15 minutes)
| When | Do this |
|---|---|
| Morning | **Review** tab → approve ~5–7 clips |
| 07:30 · 11:30 · 14:30 · 20:00 · 22:30 ET | Post the slot's clip (B4). It's 5 a day through Dec 3, then 4, then 3 |
| Evening | **Analytics** → **Pull metrics now** → see what's winning |
| Weekly | Join campaigns for the creators that keep appearing in **Needs your call** |

Leave the computer on with `serve` running if you want Autopilot to work while you're away.

---

## Decisions only you can make
- **Don't delete your old `#ad` posts** (Coinbase, MW4) until those campaigns have paid you.
- **Handle**: consider a GTA-specific name instead of `chat.clip.that` (TikTok → Edit profile).
- **Optional toggles** (Autopilot tab):
  - "Let the advisor adjust today's target" changes how many posts a day it asks for, based on results.
  - Auto-approve: only if you stop wanting to review.

## Optional upgrades (later)
- **Twitch keys**: finds the top GTA 6 clips across all of Twitch. Create an app at
  https://dev.twitch.tv/console, then set `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET` the same
  way as A4.
- **Follower count in Analytics**: make a TikTok developer app (https://developers.tiktok.com),
  set `TIKTOK_CLIENT_KEY` / `TIKTOK_CLIENT_SECRET`, then click **Connect TikTok API** in Analytics.
- **Captions on Twitch clips**:
  ```bash
  pip install faster-whisper
  ```
- **YouTube says "not a bot"**: in `config/account.json`, set
  `"cookies_from_browser": "chrome"` (or firefox/edge/safari) and stay logged into YouTube there.

## Getting Claude to run it
Open a Claude Code session on this repo/branch and type **/farm**. It scouts, researches GTA 6
trends and new campaigns, pre-screens clips, and analyses results. To let cloud sessions see your
local results, push your data from your computer:
```bash
git add data config && git commit -m "farm data" && git push
```

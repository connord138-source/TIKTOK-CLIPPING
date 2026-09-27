# Faceless long-form YouTube — plan (2026-09-27)

User approved the project 09-27 ("Tomorrow"). Goal context: a few thousand USD/month
(config/account.json `income_goal`). This is the slower, compounding lane that runs
alongside Shorts/TikTok clipping (which stays the near-term cash lane).

## Hard facts that shape everything
- **Monetization bar (YPP, full ads):** 1,000 subs + 4,000 watch hours (12 mo) or 10M
  Shorts views (90 days). **From Feb 1, 2027 new applicants need 8,000 watch hours or
  20M Shorts views**; channels already in YPP are unaffected (TechCrunch 2026-08-10).
  → Real deadline: qualify before Feb 1, 2027 or the bar doubles.
- **Inauthentic content** (ex-"repetitious"): mass-produced / templated AI spam is not
  monetizable. **Reused content:** channels built on other creators' clips get rejected at
  YPP review. → Our campaign-clip Shorts are exactly "reused content" in YouTube's eyes.
- **AI disclosure (YouTube):** an AI narrator voice on its own does NOT need the
  "altered or synthetic" label; cloning a real person's voice does; realistic synthetic
  scenes/people do. (TikTok keeps our stricter CLAUDE.md AI-label rule.)
- **RPM:** gaming ~$2–7; documentary/story formats ~$5–12 (long videos = more mid-rolls).
- **Budget:** Higgsfield balance 150.25 credits = AT the 150 floor → zero-credit pipeline
  (open-source TTS + code-rendered visuals) unless the user tops up.
- **Sourcing limits:** YouTube downloads are bot-blocked here; Twitch/Kick VODs work; we
  cannot capture gameplay ourselves.

## Channel structure (decision)
Recommend a **separate long-form channel** (same Google account, second brand channel).
YPP reviews the whole channel; a feed of campaign streamer clips (@thechatclipthat
Shorts) reads as reused content and can sink the application. Keep clipping Shorts on
"Chat Clip That!" (@thechatclipthat) and put original long-form on its own channel.

## Three format options (all on-brand: streamer/gaming culture)
**A. Streamer Numbers — data stories (recommended core).** "Kai Cenat vs IShowSpeed: who's
actually bigger in 2026", "Every record-breaking Twitch stream, ranked", "Kick vs Twitch: where
the viewers went". Visuals = code-rendered animated charts/rankings/timelines in brand style +
≤5s fair-use Twitch snippets. Most original → safest vs inauthentic/reused rules; fully
automatable; zero credits. Risk: can feel dry → needs story-first scripts + strong thumbnails.
RPM ~$3–7.

**B. Streamer mini-documentaries.** "How Jynxzi became the face of Rainbow Six", "The night the
subathon broke Twitch". Biggest-view format (doc/story RPM $5–12). Visuals lean on Twitch VOD
clips under fair use (narration throughout, clips ≤10s, heavy transformation) + graphics.
Risk: Content ID claims (streamers upload VODs to YouTube) and reused-content flags if clips
dominate. Medium risk.

**C. Esports explained.** "Why TenZ's 15HP clutch was absurd", tournament stories, meta shifts.
Loyal niche; Riot-style publisher policies allow monetized game footage, but we can't capture
gameplay and tournament VODs are hard to source here. Narrow audience, RPM ~$2–6.

**Recommendation:** A as the engine with B's storytelling ("streamer stories told with
numbers"), sprinkling short fair-use Twitch moments for proof. C later as a series.

## Production pipeline (repo: scripts/yt/, media in work/yt/)
1. **Research** — stats + facts with sources: Twitch Helix API (needs a free Twitch developer
   app from the user) + public stats pages where terms allow; fact sheet JSON with citations.
2. **Script** — Claude drafts 8–12 min (~1,300–1,800 words): 20–30s hook, chapters, on-screen
   text cues, source list. User approves topics/scripts for the first ~5 videos.
3. **Voiceover** — open-source TTS (Kokoro-82M, Apache-2.0, CPU) → $0. Options: user's own
   voice (best trust/retention), or paid TTS after a Higgsfield top-up.
4. **Visuals** — Python/PIL/matplotlib → animated charts, rankings, timelines, lower-thirds in
   brand tokens; short Twitch clips via clipper ingest; royalty-free music (YouTube Audio
   Library, user downloads the tracks).
5. **Edit** — ffmpeg assembly from a JSON edit list; burned captions optional (long-form: off,
   upload SRT instead); chapters in description.
6. **Thumbnail** — 3 PIL variants (brand fonts) for YouTube "Test & compare".
7. **Package → board** — new YouTube lane on the ops board: video file, title options,
   description + chapters + sources, tags, SRT, thumbnails, AI-disclosure verdict.
8. **User** uploads in YouTube Studio (no YouTube API connector), answers comments, applies
   for YPP when eligible. Each long-form also yields 2–3 original Shorts (our own content →
   monetizable, drives subs).

Automated: research, scripting drafts, VO, visuals, edit, captions/SRT, thumbnails,
packaging, analytics notes. User-owned: topic/script approval (early), upload + publish,
community, channel settings, YPP application. Cost: ~$0/video (+ user time ~15 min/video).

## Monetization path + realistic timeline
- 4,000 hours = 240,000 minutes ≈ 60,000 long-form views at a 4-min average view duration,
  plus 1,000 subs — in ~4 months to beat Feb 1, 2027. At 2 videos/week (~34 videos) that's
  ~1,800 views/video average: possible, but most new faceless channels need a breakout
  video; plan for 4–8 months and treat Feb 1 as a stretch goal.
- After YPP at RPM $3–8: $3k/month ≈ 400k–1M monthly views (a mid-size channel, typically
  6–18 months in). This is an asset build, not near-term cash — the clipping lane pays sooner.

## 2-week launch plan
- **Day 1:** decisions below; build pipeline skeleton; 3 voice samples → user picks.
- **Days 2–3:** research + script #1 → user approves → produce #1 + 3 thumbnails.
- **Day 4:** user uploads #1 (Tue/Thu/Sat 12–3pm ET); start #2.
- **Days 5–7:** #2 delivered; 3 Shorts cut from #1; 48h analytics check (CTR, avg view
  duration, retention dips) → adjust hooks/thumbnails.
- **Week 2:** #3 + #4 (2/week cadence); thumbnail tests; lock the format; set up a weekly
  routine (topic research → drafts for approval → production).

## Decisions for the user
1. Format: A (data stories) / B (mini-docs) / A+B hybrid (recommended) / C.
2. Channel: separate long-form channel (recommended) vs the Shorts channel.
3. Voice: free AI voice (samples) / your own voice / paid TTS (needs credit top-up).
4. Create a free Twitch developer app (2 min) for the official stats API.

Sources: TechCrunch 2026-08-10 (YPP thresholds); YouTube Blog + YouTube Help (altered or
synthetic content disclosure; YPP overview); OutlierKit / SpeakSay / EasyViral 2026 RPM
roundups (gaming $2–7, documentary $5–12).

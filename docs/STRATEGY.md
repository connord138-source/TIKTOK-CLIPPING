# Strategy — GTA 6 clip page (@chat.clip.that)

_Pivoted 2026-11-18 (eve of GTA 6 launch, Nov 19 2026). Supersedes the POV-history and generic
streamer-clipping plans._

## Thesis
GTA 6 is the biggest entertainment launch in years, and every streamer and YouTuber is
playing it at once. That produces far more clippable moments than any one person can watch.
A page that **finds the best moment within hours** and posts it as a clean, captioned 9:16
clip can pick up views while the FYP is hungry for GTA content and before clip competition
settles. The work that scales is discovery plus editing speed, so the farm automates both.
Posting stays with a human.

## Content pillars (in priority order)
1. **Streamer reactions & firsts**: "xQc's first police chase", "Kai meets Lucia". The biggest
   reach, but only clip creators whose clipping program you've joined or who gave
   permission (rights gate).
2. **Chaos & physics**: police escalations, crashes, ragdolls, gators, NPC weirdness. These
   travel even without the creator's audience.
3. **Discoveries & details**: easter eggs, secrets, "GTA 6 vs GTA 5" comparisons, map facts.
   They save and share well, and work as a series ("GTA 6 details you missed pt. 7").
4. **Moment-of-the-day news**: records, glitches going viral, patch changes. Time-sensitive:
   post within hours or skip.

Format: 18–45s (target 30s). Hook banner on top for the whole clip, word-highlight captions,
a "via {creator}" credit, loudness at −14 LUFS. First 2 seconds must make sense with zero
context, so the moment selector is told to start on the action, not the setup.

## Cadence: "the right amount"
| Phase | Dates | Posts/day | Why |
|---|---|---|---|
| launch_surge | Nov 19 – Dec 3 | **5** | Peak search and FYP demand, while moment supply is fresh. Volume finds winners on a new account |
| growth | Dec 4 – Jan 15 | **4** | Story/discovery phase. Cut volume, double down on proven pillars |
| steady | Jan 16 → | **3** | Evergreen. GTA Online (expected 2027) is the next surge, so bump back to 5 |

Guardrails built into the planner (`clipfarm/planner.py`):
- **Bounds 2–6/day.** Above ~6 on a young account, posts compete with each other and quality slips.
- **Max 2 clips per creator per day**, so the page stays a GTA page and isn't one streamer's fan page.
- **Production follows the queue.** Render only enough to fill today's open slots plus ~1 day of
  buffer, divided by your approval rate. Autopilot can't overproduce.
- **Performance advisor.** Compares the median views of the last 3 days with the prior 11 (posts
  ≥24h old only). ≥1.3× → +1/day, <0.6× → −1/day, otherwise hold. Any clip at ≥5× the median is
  flagged as a breakout, so you go back to that creator or topic. Suggest-only until you
  switch on `cadence.auto_adjust.apply`.
- Slots (ET): 07:30 · 11:30 · 14:30 · 17:30 · 20:00 · 22:30, spread evenly for the day's target.
  The gaming audience peaks in the evening. The analyst agent can re-tune slots from data.

## Money
1. **Paid clipping campaigns** (Whop Content Rewards and similar): ~$0.20–$6 per 1k verified
   views, usually with a per-clip cap and a ~10% platform fee. GTA 6 campaigns are appearing
   around launch (music promos like "Tokyo Girl" at $0.70/1k, capped at $35/clip; streamer
   programs). Join the ones whose creators the scout keeps surfacing. That also flips their
   footage to auto-clip.
2. **TikTok Creator Rewards**: needs 10k followers and videos ≥1 min. A later play is
   ≥60s "top 5 moments" compilations (raise `render.clip_seconds`).
3. Later: game-adjacent affiliate (controllers, capture cards), and selling the page.

## Risks & rules
- **Copyright / rights.** Clipping a creator without a program or permission risks DMCA strikes
  (three strikes and the account is gone) and TikTok's unoriginal-content suppression. The
  rights gate enforces this: only `campaign | permission | own` auto-render, and the rest
  waits for your call. Transformative edits (hooks, captions, curation, credit) help but
  aren't a licence.
- **Rockstar / Take-Two.** Gameplay videos are broadly tolerated. Avoid leaked or pre-release
  material and anything implying official affiliation. No Rockstar logos as branding.
- **Brand safety.** The scout hard-filters sexual content (the game has some, and early
  streams surfaced "18+" clips). TikTok is unforgiving here.
- **Bot checks.** YouTube blocks datacenter IPs. Run the farm on your own machine
  (residential IP), and set `ingest.cookies_from_browser` if it still gets challenged.
- **Labels.** Real gameplay is **not** AI-generated, so leave TikTok's AI label off. Turn it on
  only for clips that include AI visuals or voice (e.g. Higgsfield intros).
- **Account history.** The account has 7 earlier non-GTA posts, including `#ad` campaign posts
  (Coinbase, MW4). Don't delete campaign posts until their payouts clear. After that,
  archiving the off-niche posts tightens the page's signal.
- **Identity.** The handle `chat.clip.that` is generic. A GTA-specific handle would convert
  better on profile visits, but that's your call (CLAUDE.md rule 6).

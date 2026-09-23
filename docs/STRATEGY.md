# Strategy — streamer clipping (pivot locked 2026-09-22)

Goal: turn @chat.clip.that into an income-producing clipping operation, with Claude
doing ~99% of the work: find the moment, cut it, caption it, hand the user a
ready-to-post file. Money comes from **campaign bounties**, not from TikTok's own
monetization (that's a later bonus).

## 1. How the money arrives

| Path | Requirements | Timeline | Expected value |
|---|---|---|---|
| **Campaign bounties** (Whop "Content Rewards", contentrewards.com, creator Discords) | join a campaign; follow its rules; post from our account; views get verified | **from the first posted clip** | ~$0.20–$6.00 per 1k verified views depending on campaign; pools cap totals |
| Account growth → Creator Rewards | 10k followers, 100k views/30d, >1min videos | months; clips are usually <1min so this stays secondary | RPM bonus on qualifying content |
| Account as asset / paid clipping retainers | track record | after consistent results | retainers of $500–$2k/mo exist for proven clippers |
| **Agency networks** (Clipping Culture whop, Propaganda, Lumina, Shuffle) | join community / apply with posting account | community joins now; applications after first posts | steadier campaign flow, private campaigns, retainer path — see research/clipper-networks-2026-09-23.md |

**Plan of record:** bounty campaigns are the business. Everything else is optional
upside. Marginal cost per clip ≈ $0 (ffmpeg in the container; no generation credits),
so any verified payout is profit against time.

**The math that matters:** a $1.50/1k campaign paying on 100k verified views = $150 for
work that costs us nothing but minutes. The KPIs are (a) verified views per clip,
(b) campaign acceptance rate (clips not rejected), (c) clips shipped per session.

## 2. Positioning — NICHE LOCKED (2026-09-23, user decision)
**Streamers/gaming only.** Two content layers on one account:
- **Identity layer** (builds followers): streamer/esports moments — tournament clips,
  streamer reactions, chat-culture moments. This is what the handle promises.
- **Paid-filler layer** (pays bills, same audience): gaming-brand campaigns (game
  trailers, game influencer VODs).
Off-niche campaigns (podcasts, dating shows, finance faces) are skipped regardless of
rate — mixed posting trains the FYP graph against us and off-niche viewers don't
follow clip pages. High-rate off-niche pools = second-account decision (user's call).

## 2b. Positioning (original)
- Handle: **@chat.clip.that** — "CHAT, CLIP THAT 🎬". The name IS the niche: the
  moments chat begs to have clipped.
- Content: highlight clips of campaign-authorized streamers/creators. Bias campaign
  selection toward gaming/streamer culture so the account stays coherent.
- Editing signature (originality defense + brand): burned hook line top-center,
  big two-tone caption cards, tight cuts that start mid-action. Our edit, our
  moment-picking — never a re-upload of someone else's clip.

## 3. Campaign selection rules
1. **Only campaign-authorized material.** No campaign = no clip, however viral the
   streamer. (Freelance clipping breaks TikTok originality rules AND earns $0.)
2. Prefer campaigns with: clear rate + verification method, big/replenishing budget
   pool, source folders or permissive VOD access, rules we can automate (length,
   hashtags, required @tags).
3. Read every campaign's fine print before the first cut; encode its rules in the
   job's `meta.json` (`campaign` field) and the ledger entry.
4. One niche-coherent set of campaigns at a time; drop campaigns whose payouts
   stall or whose pools drain.

## 4. Algorithm playbook (clipping edition)
- **Hook in <1s:** burned text top-center states the payoff ("HE CALLED THE ONE-SHOT").
  Start the cut mid-action, ~1s before the peak line.
- **15–45s sweet spot** for pure highlights; completion rate is the ranking signal.
  Longer (60s+) only when the arc genuinely holds.
- **Captions always** — sound-off viewers; our accent-word cards double as brand.
- **End on the reaction, not after it.** Cut hard ~0.5s after the payoff lands.
- **2+/day cadence**, ≥4h apart; consistency beats bursts.
- **Hashtags:** campaign-required tags first, then 2–3 topical. No soup.
- **Series consistency:** same caption style + hook grammar every clip → profile
  visits convert to follows.

## 5. Risks & rules (account + payout survival)
1. **TikTok "unoriginal content" flags** — the clip-account killer. Mitigation: real
   editorial (our hooks, captions, cut points), varied sources, never watermarked
   re-uploads. Human posts from the app (drafts/files), never API auto-posting.
2. **Campaign rejection / view-fraud suspicion:** no engagement pods, no bought views,
   follow rules to the letter, keep VOD-timestamp records in the ledger for disputes.
3. **AI-label** whenever an AI element is visibly added (AI VO, generated b-roll).
   A plain human-made edit of human footage needs no label — don't mislabel.
4. **Copyright:** campaign authorization covers the creator's footage; background
   music in VODs can still trip Content ID — prefer moments where speech carries, or
   replace/duck music via TikTok's licensed library at post time.
5. **Payout mechanics:** Whop payouts have thresholds/timelines; track
   `payout_status` per clip in the ledger; screenshot campaign dashboards when views
   get verified.
6. **Platform concentration:** same clips repost to YT Shorts/IG Reels when campaign
   rules allow — free distribution, sometimes separately paid.

## 6. Archived: POV-history plan (pre-pivot)
The original plan (AI-generated first-person history shorts via Higgsfield; Creator
Rewards as the income path) is preserved for reference: niche analysis and algorithm
notes remain valid if we ever run an owned-content account alongside clipping.
- Idea backlog archived at `content/archive-pov-history.json` (15 scored ideas).
- Key learnings kept: >1min for Creator Rewards; originality review is the choke
  point for AI content; completion rate beats everything; 60–75s sweet spot there.
- Higgsfield toolchain (Seedance 2.5 / FLUX 3 / Shorts Studio) stays available for
  optional garnish on clips (AI b-roll, VO) and for any future owned-content lane —
  budget rules in `config/account.json` still govern any credit spend.

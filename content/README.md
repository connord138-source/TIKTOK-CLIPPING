# Content queue

`backlog.json` — the clip queue: candidate moments/VOD windows waiting to be cut,
per campaign. Entry shape:

```json
{
  "id": "q-001",
  "campaign": "whop-xyz",
  "source_url": "https://www.twitch.tv/videos/...",
  "window": "1:04:00-1:18:00",
  "why": "chat spamming CLIP IT after the 1v4; streamer screams at 1:09:30",
  "priority": 5,
  "status": "queued"
}
```

`status`: `queued → clipped` (ledger entry takes over from there) or `skipped`.
Queue refills from campaign Discords/chat replays/user tips; anything cut gets its
real record in `ledger/videos.json`.

`archive-pov-history.json` — the pre-pivot POV-history idea backlog (15 scored
ideas), kept for a possible owned-content lane. See STRATEGY §6.

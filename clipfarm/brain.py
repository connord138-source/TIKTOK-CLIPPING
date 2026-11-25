"""Claude-powered judgement calls inside the pipeline. Every function has a non-LLM
fallback (returns None) so the farm still runs without ANTHROPIC_API_KEY / `ant auth login`.

Uses the official Anthropic SDK with structured outputs (output_config.format) and the
server-side refusal fallback, per current API guidance.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .core import load_config, log

_client = None


def _cfg() -> dict:
    return load_config().get("brain", {})


def available() -> bool:
    if not _cfg().get("enabled", True):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    # credentials: env key/token, or an `ant auth login` profile on disk
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return (Path.home() / ".config" / "anthropic").exists()


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()  # ANTHROPIC_API_KEY, or an `ant auth login` profile
    return _client


def _ask(system: str, prompt, schema: dict, max_tokens: int = 8000) -> dict | None:
    """prompt: a string, or a list of content blocks (text + images)."""
    if not available():
        return None
    cfg = _cfg()
    try:
        resp = _get_client().beta.messages.create(
            model=cfg.get("model", "claude-opus-5-5"),
            max_tokens=max_tokens,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": cfg.get("effort", "medium"),
                           "format": {"type": "json_schema", "schema": schema}},
        )
    except Exception as e:  # noqa: BLE001 - brain is optional; never break the pipeline
        log(f"brain: API call failed ({type(e).__name__}: {e}); using heuristics")
        return None
    if resp.stop_reason in ("refusal", "max_tokens"):
        log(f"brain: stop_reason={resp.stop_reason}; using heuristics")
        return None
    text = next((b.text for b in resp.content if b.type == "text"), None)
    try:
        return json.loads(text) if text else None
    except json.JSONDecodeError:
        return None


SYSTEM_EDITOR = """You are the head editor of a TikTok clip page about GTA 6 (Grand Theft Auto VI),
which launched November 19, 2026. You choose which moments from source videos become 15-45s
vertical clips, and write the on-screen hook and the post caption.

What performs: a moment that makes sense with zero context in the first 2 seconds; chaos
(police chases, crashes, physics, NPC weirdness, glitches), streamer reactions, discoveries
(easter eggs, secrets, details), comparisons to GTA 5, and big emotional beats. What flops:
menus, loading, slow driving, sponsor reads, intros/outros, talking about the video itself,
moments that need the previous 5 minutes to understand.

Be picky. A viewer swipes away in two seconds, so a clip needs a visible payoff: a chase
escalating, a crash, an explosion, a shootout, a stunt, something absurd or funny, a strong
reaction, a reveal. Ordinary travel from A to B, exploring quietly, shopping, customising or
talking over calm footage is boring even when the video is popular. If only one window is
good, return one. If none are, return none: another video will be tried instead.

Hooks: <= 7 words, curiosity or stakes, no clickbait lies, no emojis spam (0-1 emoji). When you
have frames, the hook must describe what is actually visible in the window you picked.
Captions: 1 short line + 3-6 hashtags; always include #gta6. Credit the creator in the caption
as "via <channel>". Never invent events that are not in the transcript.

Some sources are pure gameplay with no commentary. Their windows carry no transcript, only a
note about audio activity (loud bursts usually mean gunfire, crashes, sirens, explosions).
For those, prefer the windows with the most activity, and write the hook and caption from what
the video's title promises. Keep them general ("GTA 6 free roam is unreal") rather than
claiming a specific event you cannot see."""

_MOMENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "window": {"type": "integer", "description": "index of the candidate window"},
                    "start": {"type": "number", "description": "absolute start second"},
                    "end": {"type": "number", "description": "absolute end second"},
                    "score": {"type": "integer", "description": "0-100 predicted clip strength"},
                    "hook": {"type": "string"},
                    "caption": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                },
                "required": ["window", "start", "end", "score", "hook", "caption", "hashtags", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["picks"],
    "additionalProperties": False,
}


def _image_block(path: Path) -> dict:
    import base64
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(Path(path).read_bytes()).decode()}}


def pick_moments(source: dict, windows: list[dict], max_picks: int, length: tuple[int, int],
                 previews: list | None = None) -> list[dict] | None:
    """windows: [{start,end,text,heuristic}] -> picks with refined bounds + packaging.
    previews: optional list (same order) of 2x2 frame sheets, one per window, or None."""
    if not windows:
        return None
    lines = [f"SOURCE: {source.get('title')!r} by {source.get('channel')} "
             f"({source.get('platform')}, {source.get('views') or 0} views)",
             f"Pick up to {max_picks} clips, each {length[0]}-{length[1]}s. You may move start/end "
             "within ±8s of the window to land on clean sentence boundaries. Return an empty list "
             "if nothing would work as a standalone TikTok.", ""]
    has_frames = bool(previews) and any(previews)
    if has_frames:
        lines.insert(2, "Each window may be followed by an image: four frames from that window in reading "
                        "order (start to end). Judge mainly from what you can SEE happening. Do not pick a "
                        "window whose frames show calm driving or walking, menus, maps, loading screens, a "
                        "face talking to camera with no gameplay, or four near-identical frames.")
    content: list = [{"type": "text", "text": "\n".join(lines)}]
    for i, w in enumerate(windows):
        content.append({"type": "text", "text":
                        f"[window {i}] {w['start']:.1f}s-{w['end']:.1f}s heuristic={w.get('heuristic', 0):.0f}\n"
                        + (w.get("text") or "(no transcript - judge from the frames, title and position)")})
        if has_frames and i < len(previews) and previews[i]:
            content.append(_image_block(previews[i]))
    out = _ask(SYSTEM_EDITOR, content if has_frames else "\n\n".join(c["text"] for c in content), _MOMENTS_SCHEMA)
    if not out:
        return None
    picks = []
    for p in out.get("picks", [])[:max_picks]:
        if not 0 <= p["window"] < len(windows):
            continue
        w = windows[p["window"]]
        start = max(w["start"] - 8, min(p["start"], w["end"]))
        end = min(w["end"] + 8, max(p["end"], start + length[0]))
        end = min(end, start + length[1])
        picks.append({**p, "start": round(start, 2), "end": round(end, 2)})
    return picks


_QUERIES_SCHEMA = {
    "type": "object",
    "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
    "required": ["queries"],
    "additionalProperties": False,
}


def suggest_queries(top_titles: list[str], winning_hooks: list[str], n: int = 5) -> list[str] | None:
    prompt = (f"Recent high-velocity GTA 6 uploads:\n- " + "\n- ".join(top_titles[:40]) +
              "\n\nOur best-performing clip hooks:\n- " + ("\n- ".join(winning_hooks[:15]) or "(none yet)") +
              f"\n\nPropose {n} short YouTube search queries (2-5 words, each starting with 'GTA 6') "
              "that would surface FRESH clippable footage about the topics trending right now "
              "(specific discoveries, glitches, missions, places, characters, streamer moments).")
    out = _ask(SYSTEM_EDITOR, prompt, _QUERIES_SCHEMA, max_tokens=2000)
    return [q.strip() for q in out["queries"] if q.strip()][:n] if out else None


SYSTEM_REVIEWER = """You are the final quality check for a TikTok clip page about GTA 6. You are shown
one image: six frames taken evenly through a finished vertical clip (left to right, top to
bottom). A hook banner sits near the top and there may be word captions lower down.

Approve only if all of these hold:
- it is clearly video-game footage that could be GTA 6 (or a streamer reacting to it), not
  something unrelated;
- something visibly happens across the frames (movement, action, a change of scene). Reject
  menus, loading screens, maps, a static or frozen image, black frames, or a talking-head
  intro/outro;
- no nudity or sexual content (set nsfw true if there is any);
- the hook text is readable and does not obviously contradict what the frames show.

quality is 0-100: how likely this clip is to hold a viewer who has no context. Use the range:
90+ a clear payoff anyone would rewatch; 70-89 real action or a real reaction throughout;
40-69 gameplay where little happens (calm driving, walking, looking around, talking over quiet
footage); below 40 broken, static or off-topic. Boring is a reason to score under 70."""

_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "approve": {"type": "boolean"},
        "quality": {"type": "integer"},
        "nsfw": {"type": "boolean"},
        "reason": {"type": "string", "description": "one sentence"},
    },
    "required": ["approve", "quality", "nsfw", "reason"],
    "additionalProperties": False,
}


def review_clip(grid: Path, hook: str, source_title: str) -> dict | None:
    """Look at the clip's 6-frame contact sheet. None if the brain is unavailable."""
    if not available() or not grid or not Path(grid).is_file():
        return None
    content = [
        _image_block(grid),
        {"type": "text", "text": f"Hook on the clip: {hook!r}\nSource video title: {source_title!r}\n"
                                 "Give your verdict."},
    ]
    return _ask(SYSTEM_REVIEWER, content, _REVIEW_SCHEMA, max_tokens=4000)

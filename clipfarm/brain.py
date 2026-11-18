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


def _ask(system: str, prompt: str, schema: dict, max_tokens: int = 8000) -> dict | None:
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

Hooks: <= 7 words, curiosity or stakes, no clickbait lies, no emojis spam (0-1 emoji).
Captions: 1 short line + 3-6 hashtags; always include #gta6. Credit the creator in the caption
as "via <channel>". Never invent events that are not in the transcript."""

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


def pick_moments(source: dict, windows: list[dict], max_picks: int, length: tuple[int, int]) -> list[dict] | None:
    """windows: [{start,end,text,heuristic}] -> picks with refined bounds + packaging."""
    if not windows:
        return None
    lines = [f"SOURCE: {source.get('title')!r} by {source.get('channel')} "
             f"({source.get('platform')}, {source.get('views') or 0} views)",
             f"Pick up to {max_picks} clips, each {length[0]}-{length[1]}s. You may move start/end "
             "within ±8s of the window to land on clean sentence boundaries. Return an empty list "
             "if nothing would work as a standalone TikTok.", ""]
    for i, w in enumerate(windows):
        lines.append(f"[window {i}] {w['start']:.1f}s-{w['end']:.1f}s heuristic={w.get('heuristic', 0):.0f}")
        lines.append(w.get("text") or "(no transcript - judge from title/position only)")
        lines.append("")
    out = _ask(SYSTEM_EDITOR, "\n".join(lines), _MOMENTS_SCHEMA)
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

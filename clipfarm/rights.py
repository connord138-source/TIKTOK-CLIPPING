"""Rights gate. Every candidate carries a rights level resolved from config/sources.json.

Levels:
  campaign    – source is in an active paid clipping campaign (Whop/Content Rewards etc.)
  permission  – creator has an open clipping program / gave explicit permission
  own         – the account owner's own gameplay capture
  official    – publisher press assets (trailers); transformative edits only
  unverified  – discovered by the scout, no known program  -> needs a human decision
  blocked     – never clip (takedowns, creator asked, etc.)

The policy (config/sources.json -> policy) decides which levels auto-render. Unverified
material is surfaced in the dashboard so the user can one-click upgrade the *channel*.
"""
from __future__ import annotations

from .core import load_sources

LEVELS = ["campaign", "permission", "own", "official", "unverified", "blocked"]
DEFAULT_AUTO = ["campaign", "permission", "own"]


def _norm(s: str | None) -> str:
    return (s or "").strip().lower().lstrip("@")


def channel_key(platform: str, ident: str | None) -> str:
    return f"{platform}:{_norm(ident)}"


def find_channel(platform: str, *idents: str | None) -> dict | None:
    src = load_sources()
    keys = {_norm(i) for i in idents if i}
    for ch in src.get("channels", []):
        if ch.get("platform") != platform:
            continue
        if keys & {_norm(ch.get("id")), _norm(ch.get("login")), _norm(ch.get("name"))}:
            return ch
    return None


def resolve(platform: str, *idents: str | None) -> tuple[str, str | None]:
    """-> (rights_level, campaign_id)"""
    ch = find_channel(platform, *idents)
    if not ch:
        return "unverified", None
    return ch.get("rights", "unverified"), ch.get("campaign_id")


def auto_render_allowed(level: str) -> bool:
    policy = load_sources().get("policy", {})
    return level in policy.get("auto_render", DEFAULT_AUTO)


def campaign(campaign_id: str | None) -> dict | None:
    if not campaign_id:
        return None
    return next((c for c in load_sources().get("campaigns", []) if c.get("id") == campaign_id), None)

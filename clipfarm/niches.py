"""Niches: what the farm clips. GTA 6 is the first one; each niche has its own searches,
relevance words, hashtags and a brief that tells Claude what the page is about.

Stored under `niches` in config/account.json once the user edits them in the dashboard.
Until then the single default niche is built from the original GTA 6 settings.
"""
from __future__ import annotations

import re

from .core import load_config, save_config

GTA_BRIEF = (
    "Clips from GTA 6 (Grand Theft Auto VI), which launched November 19, 2026. What performs: "
    "chaos (police chases, crashes, physics, NPC weirdness, glitches), streamer reactions, "
    "discoveries (easter eggs, secrets, details), comparisons to GTA 5, and big story beats. "
    "What flops: menus, loading, slow driving, sponsor reads, intros and outros.")
GTA_RELEVANCE = r"gta\s*(6|vi)\b|gta6|gtavi|grand theft auto (6|vi)|vice city|leonida|\blucia\b"
GTA_KEYWORDS = ["cop", "police", "wanted", "star", "chase", "crash", "heist", "gun", "shoot", "gator",
                "alligator", "florida", "vice city", "lucia", "jason", "bank", "rob", "glitch", "bug",
                "physics", "npc", "secret", "easter egg", "helicopter", "jet", "boat", "beach", "money",
                "gta 5", "gta five", "detail", "ragdoll", "explosion", "swat", "tank", "leonida"]


def _default(cfg: dict) -> dict:
    sc = cfg.get("scout", {})
    return {"id": "gta6", "name": "GTA 6", "brief": GTA_BRIEF, "enabled": True,
            "queries": sc.get("queries") or ["GTA 6", "GTA 6 funny moments", "GTA 6 police chase"],
            "relevance": sc.get("relevance_regex", GTA_RELEVANCE),
            "keywords": GTA_KEYWORDS,
            "hashtags": cfg.get("style", {}).get("hashtags_core", ["#gta6", "#gtavi", "#gta", "#gaming", "#fyp"]),
            "twitch_game": sc.get("twitch_game_name", "Grand Theft Auto VI")}


def all_niches() -> list[dict]:
    cfg = load_config()
    saved = cfg.get("niches")
    return [dict(n) for n in saved] if saved else [_default(cfg)]


def enabled() -> list[dict]:
    return [n for n in all_niches() if n.get("enabled", True)]


def get(niche_id: str | None) -> dict:
    """The niche with this id, else the first one (older candidates and clips carry no niche)."""
    items = all_niches()
    return next((n for n in items if n["id"] == niche_id), items[0])


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "niche"


def relevance_pattern(niche: dict) -> str:
    """`relevance` may be a regex, or plain words separated by commas."""
    raw = (niche.get("relevance") or "").strip()
    if not raw:
        return r"(?!)"  # matches nothing: a niche with no relevance words accepts nothing by title
    if "," in raw and not re.search(r"[\\|()\[\]]", raw):
        words = [re.escape(w.strip()) for w in raw.split(",") if w.strip()]
        return r"(?<!\w)(" + "|".join(words) + r")(?!\w)"
    return raw


def is_relevant(niche: dict, text: str) -> bool:
    try:
        return bool(re.search(relevance_pattern(niche), text or "", re.I))
    except re.error:
        return False


def match(text: str) -> dict | None:
    """Which enabled niche a title belongs to (first match wins)."""
    return next((n for n in enabled() if is_relevant(n, text)), None)


def clean(n: dict) -> dict:
    def listify(v):
        if isinstance(v, str):
            v = re.split(r"[\n,]", v)
        return [x.strip() for x in (v or []) if str(x).strip()]
    name = (n.get("name") or "").strip()
    if not name:
        raise ValueError("a niche needs a name")
    tags = ["#" + t.lstrip("#").replace(" ", "").lower() for t in listify(n.get("hashtags"))]
    return {"id": n.get("id") or slug(name), "name": name, "brief": (n.get("brief") or "").strip(),
            "enabled": bool(n.get("enabled", True)), "queries": listify(n.get("queries")),
            "relevance": (n.get("relevance") or "").strip(), "keywords": listify(n.get("keywords")),
            "hashtags": [t for t in tags if t != "#"], "twitch_game": (n.get("twitch_game") or "").strip() or None}


def upsert(n: dict) -> dict:
    n = clean(n)
    if not n["queries"]:
        raise ValueError("add at least one search so the farm can find videos for this niche")
    try:
        re.compile(relevance_pattern(n))
    except re.error as e:
        raise ValueError(f"the relevance words are not valid: {e}") from None
    items = all_niches()
    items = [n if x["id"] == n["id"] else x for x in items] if any(x["id"] == n["id"] for x in items) else items + [n]
    cfg = load_config()
    cfg["niches"] = items
    save_config(cfg)
    return n


def remove(niche_id: str) -> None:
    items = [x for x in all_niches() if x["id"] != niche_id]
    if not items:
        raise ValueError("keep at least one niche")
    cfg = load_config()
    cfg["niches"] = items
    save_config(cfg)

"""Moment finding: transcript + YouTube "most replayed" heatmap + keyword energy -> windows,
then Claude (brain) picks/refines/packages the best ones. Heuristic-only when brain is off.
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path

from . import brain
from .core import WORK_DIR, load_config, log, run, ytdlp_cmd

EXCITE = ["no way", "oh my god", "omg", "what the", "bro", "let's go", "lets go", "holy", "wait",
          "dude", "crazy", "insane", "clip that", "clip it", "chat", "oh no", "get out", "run",
          "help", "nah", "yo", "what is that", "are you serious", "look at this", "bruh", "wow"]
GTA = ["cop", "police", "wanted", "star", "chase", "crash", "heist", "gun", "shoot", "gator",
       "alligator", "florida", "vice city", "lucia", "jason", "bank", "rob", "glitch", "bug",
       "physics", "npc", "secret", "easter egg", "helicopter", "jet", "boat", "beach", "money",
       "gta 5", "gta five", "detail", "ragdoll", "explosion", "swat", "tank", "leonida"]
LAUGH = ["[laughter]", "[laughs]", "haha", "hahaha", "lmao"]
DEAD = ["subscribe", "sponsor", "link in the description", "like and subscribe", "patreon",
        "use code", "welcome back", "today we're", "in this video", "smash that"]


# ---------------------------------------------------------------- transcripts
def words_from_json3(path: Path) -> list[dict]:
    d = json.loads(path.read_text(encoding="utf-8"))
    words = []
    for ev in d.get("events", []):
        segs = ev.get("segs")
        if not segs:
            continue
        t0 = ev.get("tStartMs", 0)
        for s in segs:
            txt = (s.get("utf8") or "").strip()
            if not txt or txt in ("[", "]"):
                continue
            if txt in ("__", "[__]", "[ __ ]"):
                txt = "****"  # YouTube bleep: keep as a profanity marker
            words.append({"t": (t0 + s.get("tOffsetMs", 0)) / 1000.0, "w": txt})
    words.sort(key=lambda w: w["t"])
    for i, w in enumerate(words):  # end = next word start, capped at 1.2s
        nxt = words[i + 1]["t"] if i + 1 < len(words) else w["t"] + 0.6
        w["e"] = round(min(nxt, w["t"] + 1.2), 3)
    return words


def fetch_youtube_words(cand: dict) -> list[dict]:
    work = WORK_DIR / cand["id"].replace(":", "_")
    work.mkdir(parents=True, exist_ok=True)
    existing = glob.glob(str(work / "subs*.json3"))
    if not existing:
        run(ytdlp_cmd() + ["--skip-download", "--write-subs", "--write-auto-subs",
                           "--sub-langs", "en,en-orig,en-US,en.*", "--sub-format", "json3",
                           "-o", str(work / "subs.%(ext)s"), cand["url"]], timeout=180)
        existing = glob.glob(str(work / "subs*.json3"))
    if not existing:
        return []
    # prefer manual subs (no "-orig"/auto suffix ambiguity: largest file usually auto w/ words)
    best = max(existing, key=lambda p: Path(p).stat().st_size)
    return words_from_json3(Path(best))


def whisper_words(media: Path) -> list[dict]:
    """Optional ASR for sources without captions (Twitch/Kick/own footage)."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        return []
    model_name = load_config().get("render", {}).get("whisper_model", "small.en")
    model = WhisperModel(model_name, device="auto", compute_type="int8")
    segs, _ = model.transcribe(str(media), word_timestamps=True, vad_filter=True)
    words = []
    for seg in segs:
        for w in seg.words or []:
            words.append({"t": round(w.start, 3), "e": round(w.end, 3), "w": w.word.strip()})
    return words


# ---------------------------------------------------------------- scoring
def _count(text: str, terms: list[str]) -> int:
    return sum(len(re.findall(r"(?<!\w)" + re.escape(t) + r"(?!\w)", text)) for t in terms)


def window_text(words: list[dict], start: float, end: float) -> str:
    return " ".join(w["w"] for w in words if start <= w["t"] < end)


def heatmap_value(heatmap: list, start: float, end: float) -> float | None:
    if not heatmap:
        return None
    vals = [v for (s, e, v) in heatmap if e > start and s < end]
    return sum(vals) / len(vals) if vals else 0.0


def score_window(words: list[dict], heatmap: list, start: float, end: float, total: float) -> float:
    text = window_text(words, start, end).lower()
    dur = max(end - start, 1)
    n_words = len(text.split())
    s = min(n_words / dur, 4.0) * 4                      # speech energy (max 16)
    kw = (_count(text, EXCITE) * 3 + _count(text, GTA) * 1.5 + _count(text, LAUGH) * 4
          + text.count("****") * 2)                      # bleeped profanity = heated moment
    s += min(kw, 60)                                     # capped: keyword spam can't outvote replays
    s -= _count(text, DEAD) * 12
    if start < 45:
        s -= 10                                          # intros rarely clip well
    if total and end > total - 30:
        s -= 8                                           # outros
    hv = heatmap_value(heatmap, start, end)
    if hv is not None:
        s += hv * 80                                     # "most replayed" (0-1) is the best signal we have
    return round(s, 2)


def _snap(words: list[dict], t: float, direction: int, slack: float = 3.0) -> float:
    """Move t to a pause boundary (gap >= .35s) within slack seconds."""
    options = []
    for i in range(len(words) - 1):
        gap_start, gap_end = words[i]["e"], words[i + 1]["t"]
        if gap_end - gap_start < 0.35:
            continue
        cand = gap_end - 0.1 if direction < 0 else gap_start + 0.25
        if abs(cand - t) <= slack:
            options.append(cand)
    best = min(options, key=lambda c: abs(c - t)) if options else t
    return round(max(best, 0.0), 2)


def candidate_windows(words: list[dict], heatmap: list, total: float, length: int,
                      top: int, min_gap: float = 45) -> list[dict]:
    if not total:
        total = (words[-1]["e"] if words else 0) or (heatmap[-1][1] if heatmap else 0)
    if total <= length:
        return [{"start": 0.0, "end": float(total or length), "heuristic": 0.0,
                 "text": window_text(words, 0, total or length)}]
    scored = []
    t = 0.0
    while t + length <= total:
        scored.append((score_window(words, heatmap, t, t + length, total), t))
        t += 5.0
    scored.sort(reverse=True)
    chosen: list[dict] = []
    for sc, st in scored:
        if any(abs(st - c["start"]) < length + min_gap for c in chosen):
            continue
        s = _snap(words, st, -1)
        e = _snap(words, st + length, +1)
        chosen.append({"start": s, "end": max(e, s + 5), "heuristic": sc,
                       "text": window_text(words, s, e)})
        if len(chosen) >= top:
            break
    return chosen


# ---------------------------------------------------------------- entry
def find_moments(cand: dict, words: list[dict]) -> list[dict]:
    """-> [{start,end,score,hook,caption,hashtags,reason,source:'brain'|'heuristic'}]"""
    cfg = load_config()
    rc = cfg.get("render", {})
    lo, hi = rc.get("clip_seconds", [18, 45])
    target = rc.get("clip_target_seconds", 30)
    max_clips = cfg.get("produce", {}).get("max_clips_per_source", 2)
    total = float(cand.get("duration") or 0)

    if cand.get("forced_window"):
        s, e = cand["forced_window"]
        windows = [{"start": s, "end": e, "heuristic": 50, "text": window_text(words, s, e)}]
    elif cand.get("platform") == "twitch" or (total and total <= hi + 5):
        windows = [{"start": 0.0, "end": float(min(total or hi, hi)), "heuristic": 50,
                    "text": window_text(words, 0, hi)}]
    else:
        if not words and not cand.get("heatmap"):
            log(f"moments {cand['id']}: no transcript and no heatmap -> no signal")
            return []
        windows = candidate_windows(words, cand.get("heatmap") or [], total, target,
                                    top=rc.get("windows_to_brain", 6))

    picks = brain.pick_moments(cand, windows, max_clips, (lo, hi))
    if picks is not None:
        for p in picks:
            p["source"] = "brain"
        return picks

    # heuristic fallback: top windows above threshold, generic packaging
    min_h = rc.get("heuristic_min_score", 20)
    out = []
    for w in windows[:max_clips]:
        if w["heuristic"] < min_h and not cand.get("forced_window") and cand.get("platform") != "twitch":
            continue
        out.append({"start": w["start"], "end": w["end"], "score": int(min(w["heuristic"], 100)),
                    "hook": heuristic_hook(cand, w.get("text", "")),
                    "caption": f"{(cand.get('title') or '')[:80]} — via {cand.get('channel') or 'source'}",
                    "hashtags": [], "reason": "heuristic window", "source": "heuristic"})
    return out


def heuristic_hook(cand: dict, text: str) -> str:
    title = re.sub(r"[\[\(].*?[\]\)]|\|.*$", "", cand.get("title") or "").strip()
    title = re.sub(r"(?i)\bgta\s*(6|vi)\b[:\-– ]*", "", title).strip()
    words = title.split()[:7]
    return ("GTA 6: " + " ".join(words)) if words else "GTA 6 moment you missed"

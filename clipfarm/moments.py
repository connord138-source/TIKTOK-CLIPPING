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


# ---------------------------------------------------------------- audio energy (no-commentary gameplay)
def audio_energy(cand: dict) -> list[float]:
    """Per-second loudness (dB RMS) of the whole source. Used when there is no speech to read:
    gunfire, crashes, sirens and explosions show up as bursts above the video's normal level."""
    work = WORK_DIR / cand["id"].replace(":", "_")
    work.mkdir(parents=True, exist_ok=True)
    cache = work / "energy.json"
    if cache.exists():
        return json.loads(cache.read_text())
    url = cand["url"]
    if not re.match(r"https?://", url):
        media = Path(url.strip().strip('"')).expanduser()
    else:
        limit = load_config().get("produce", {}).get("max_source_minutes", 240)
        if (cand.get("duration") or 0) > limit * 60:
            log(f"moments {cand['id']}: {cand['duration'] / 60:.0f} min is over the {limit} min limit for audio analysis")
            return []
        hits = [h for h in glob.glob(str(work / "audio.*")) if not h.endswith((".part", ".ytdl"))]
        if not hits:
            proc = run(ytdlp_cmd() + ["-f", "ba[abr<=96]/ba/b[height<=360]/b", "-o", str(work / "audio.%(ext)s"), url],
                       timeout=1200)
            hits = [h for h in glob.glob(str(work / "audio.*")) if not h.endswith((".part", ".ytdl"))]
            if not hits:
                log(f"moments {cand['id']}: audio download failed: " + (proc.stderr.strip().splitlines() or ["?"])[-1][:200])
                return []
        media = Path(hits[0])
    proc = run(["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-i", str(media), "-vn", "-af",
                "aresample=8000,asetnsamples=n=8000:p=0,astats=metadata=1:reset=1,"
                "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-", "-f", "null", "-"], timeout=1200)
    rms = []
    for m in re.finditer(r"RMS_level=(-?inf|-?[\d.]+)", proc.stdout):
        rms.append(-90.0 if "inf" in m.group(1) else max(float(m.group(1)), -90.0))
    if rms:
        cache.write_text(json.dumps([round(v, 1) for v in rms]))
    return rms


def energy_windows(rms: list[float], total: float, length: int, top: int, min_gap: float = 45) -> list[dict]:
    """Rank windows by how far and how often the audio jumps above the video's usual level."""
    n = len(rms)
    if n < length + 10:
        return []
    ordered = sorted(rms)
    med, p95 = ordered[n // 2], ordered[int(n * 0.95)]
    span = max(p95 - med, 3.0)
    z = [max(-1.0, min((v - med) / span, 2.0)) for v in rms]
    burst = [1 if i and rms[i] - rms[i - 1] >= 6 and z[i] > 0.5 else 0 for i in range(n)]
    half = max(length // 2, 1)
    scored = []
    for t in range(0, n - length, 5):
        seg = z[t:t + length]
        s = sum(sorted(seg, reverse=True)[:half]) / half * 30 + sum(burst[t:t + length]) * 3
        if t < 45:
            s -= 10
        if total and t + length > total - 30:
            s -= 8
        scored.append((round(s, 2), t))
    scored.sort(reverse=True)
    chosen: list[dict] = []
    for sc, t in scored:
        if any(abs(t - c["_t"]) < length + min_gap for c in chosen):
            continue
        first = next((i for i in range(t, t + length) if z[i] > 0.8), t)   # start ~3s before the action
        start = float(max(0, min(first - 3, t + 8)))
        end = float(min(start + length, n))
        peak = max(rms[int(start):int(end)]) - med
        chosen.append({"_t": t, "start": start, "end": end, "heuristic": sc, "no_speech": True,
                       "text": f"(no speech in this video) audio activity: {sum(burst[int(start):int(end)])} sudden loud "
                               f"bursts, peak {peak:+.0f} dB above the video's normal level"})
        if len(chosen) >= top:
            break
    for c in chosen:
        c.pop("_t")
    return chosen


# ---------------------------------------------------------------- previews (what Claude looks at)
def _preview_sheet(cand: dict, idx: int, start: float, end: float) -> Path | None:
    """A 2x2 sheet of four frames spread across one candidate window. None if it can't be made."""
    work = WORK_DIR / cand["id"].replace(":", "_") / "previews"
    work.mkdir(parents=True, exist_ok=True)
    sheet = work / f"w{idx}_{int(start)}.jpg"
    if sheet.exists():
        return sheet
    dur = max(end - start, 4.0)
    url = cand["url"]
    try:
        if re.match(r"https?://", url):
            tag = f"p{idx}_{int(start)}"
            hits = [h for h in glob.glob(str(work / f"{tag}.*")) if not h.endswith((".part", ".ytdl", ".jpg"))]
            if not hits:
                run(ytdlp_cmd() + ["-f", "bv*[height<=360]/b[height<=360]/wv*/w", "--download-sections",
                                   f"*{start:.1f}-{end:.1f}", "-o", str(work / f"{tag}.%(ext)s"), url], timeout=180)
                hits = [h for h in glob.glob(str(work / f"{tag}.*")) if not h.endswith((".part", ".ytdl", ".jpg"))]
            if not hits:
                return None
            src, seek = Path(hits[0]), []
        else:
            src, seek = Path(url.strip().strip('"')).expanduser(), ["-ss", f"{start:.2f}", "-t", f"{dur:.2f}"]
        run(["ffmpeg", "-y", "-loglevel", "error", *seek, "-i", str(src), "-an", "-vf",
             f"fps=4/{dur:.2f},scale=384:216:force_original_aspect_ratio=decrease,pad=384:216:(ow-iw)/2:(oh-ih)/2,tile=2x2",
             "-frames:v", "1", "-q:v", "5", str(sheet)], timeout=120)
        if src.parent == work:
            src.unlink(missing_ok=True)   # keep only the small sheet
    except Exception as e:  # noqa: BLE001 - previews are a bonus; never block a clip on them
        log(f"preview {cand['id']} window {idx}: {e}")
    return sheet if sheet.exists() and sheet.stat().st_size > 500 else None


def window_previews(cand: dict, windows: list[dict]) -> list[Path | None]:
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(lambda iw: _preview_sheet(cand, iw[0], iw[1]["start"], iw[1]["end"]), enumerate(windows)))


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
        visual = brain.available() and cfg.get("produce", {}).get("visual_pick", True)
        top = max(rc.get("windows_to_brain", 6), 8) if visual else rc.get("windows_to_brain", 6)
        if words or cand.get("heatmap"):
            windows = candidate_windows(words, cand.get("heatmap") or [], total, target, top=top)
        else:  # gameplay with no commentary: find the action from the audio instead
            log(f"moments {cand['id']}: no speech or replay data; analysing the audio for action")
            windows = energy_windows(audio_energy(cand), total, target, top=top)
            if not windows:
                log(f"moments {cand['id']}: no usable signal (no speech, no replay data, audio analysis empty)")
                return []

    previews = None
    if brain.available() and cfg.get("produce", {}).get("visual_pick", True) and len(windows) > 1:
        previews = window_previews(cand, windows)   # Claude sees frames from every candidate moment
        log(f"moments {cand['id']}: {sum(1 for p in previews if p)}/{len(windows)} candidate moments have preview frames")
    picks = brain.pick_moments(cand, windows, max_clips, (lo, hi), previews)
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

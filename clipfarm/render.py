"""Render: source section -> 1080x1920 TikTok clip with hook title, word-highlight captions,
creator credit, loudness normalisation; then automated QC (probe, audio, black frames,
thumbnail + 6-frame contact grid for review without watching).
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path

from . import rights
from .core import CLIPS_DIR, ROOT, WORK_DIR, load_config, log, run, ytdlp_cmd

W, H = 1080, 1920

# vertical anchors per layout: (hook_y, caption_y) in ASS coords (alignment 8 = top-centre)
LAYOUT_TEXT_Y = {"blurpad": (330, 1330), "zoom": (220, 1560), "split": (60, 1700)}


# ---------------------------------------------------------------- ingest
def fetch_source(cand: dict, start: float, end: float, pad: float = 1.0) -> tuple[Path, float]:
    """-> (media_path, base_offset). Clip time t in source == local time (t - base)."""
    url = cand["url"]
    if not re.match(r"https?://", url):
        local = Path(url.strip().strip('"')).expanduser()
        if local.exists():
            return local, 0.0
        raise RuntimeError(f"file not found: {local}")
    work = WORK_DIR / cand["id"].replace(":", "_")
    work.mkdir(parents=True, exist_ok=True)
    fmt = "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b"
    dur = float(cand.get("duration") or 0)
    whole = cand.get("platform") == "twitch" or (dur and dur <= 120)
    if whole:
        out_tpl, base = str(work / "full.%(ext)s"), 0.0
        pattern = "full.*"
        extra: list[str] = []
    else:
        s, e = max(0.0, start - pad), end + pad
        tag = f"sec_{int(s)}_{int(e)}"
        out_tpl, base, pattern = str(work / f"{tag}.%(ext)s"), s, f"{tag}.*"
        extra = ["--download-sections", f"*{s:.2f}-{e:.2f}", "--force-keyframes-at-cuts"]
    hits = [p for p in glob.glob(str(work / pattern)) if not p.endswith((".part", ".ytdl"))]
    if not hits:
        proc = run(ytdlp_cmd() + ["-f", fmt, "--merge-output-format", "mp4", "-o", out_tpl, *extra, url],
                   timeout=900)
        hits = [p for p in glob.glob(str(work / pattern)) if not p.endswith((".part", ".ytdl"))]
        if not hits:
            raise RuntimeError("download failed: " + (proc.stderr.strip().splitlines() or ["?"])[-1][:300])
    if not whole:
        # A section can start a few seconds early (at the previous keyframe). Its end is exact, so
        # work the real start out from the file's length; otherwise captions run late by that much.
        actual, wanted = probe(Path(hits[0]))["duration"], e - s
        if 0.3 < actual - wanted < 15:
            log(f"sync {cand['id']}: section is {actual - wanted:.1f}s longer than asked; shifting captions to match")
            base = e - actual
    return Path(hits[0]), base


# ---------------------------------------------------------------- captions (ASS)
def _ass_time(t: float) -> str:
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _clean(text: str) -> str:
    text = text.replace("[ __ ]", "****").replace("\\", "").replace("{", "(").replace("}", ")")
    return re.sub(r"\s+", " ", text).strip()


def _wrap(text: str, width: int = 22) -> str:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return r"\N".join(lines[:3])


def build_ass(words: list[dict], start: float, end: float, hook: str, credit: str,
              layout: str, rc: dict) -> str:
    font = rc.get("font", "Arial Black")
    hook_y, cap_y = LAYOUT_TEXT_Y.get(layout, LAYOUT_TEXT_Y["blurpad"])
    hook_secs = rc.get("hook_seconds", 0)  # 0 = whole clip
    hl = rc.get("caption_highlight", "&H00E5FF&")  # ASS &HBBGGRR&: amber
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,{font},74,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,3,14,0,8,60,60,{hook_y},1
Style: Cap,{font},82,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,8,50,50,{cap_y},1
Style: Credit,{font},34,&H00E6E6E6,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,3,0,2,40,40,70,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dur = end - start
    ev = []
    if hook:
        ev.append(f"Dialogue: 2,{_ass_time(0)},{_ass_time(hook_secs or dur)},Hook,,0,0,0,,"
                  f"{{\\fad(150,0)}}{_wrap(_clean(hook).upper(), 20)}")
    if credit:
        ev.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(dur)},Credit,,0,0,0,,{_clean(credit)}")
    if rc.get("captions", True):
        seg = [w for w in words if start <= w["t"] < end
               and not re.fullmatch(r"\[.*\]|>>", w["w"].strip())]  # drop [laughter], speaker marks
        chunks, cur = [], []
        for w in seg:  # 1-3 words per chunk, break on pauses
            if cur and (len(cur) >= 3 or w["t"] - cur[-1]["e"] > 0.45):
                chunks.append(cur)
                cur = []
            cur.append(w)
        if cur:
            chunks.append(cur)
        for ci, ch in enumerate(chunks):
            c_end = chunks[ci + 1][0]["t"] if ci + 1 < len(chunks) else ch[-1]["e"]
            c_end = min(c_end, ch[-1]["e"] + 0.6)
            for wi, w in enumerate(ch):  # one event per word = moving highlight
                w_start = w["t"]
                w_end = ch[wi + 1]["t"] if wi + 1 < len(ch) else c_end
                parts = []
                for j, x in enumerate(ch):
                    txt = _clean(x["w"]).upper()
                    parts.append(f"{{\\c{hl}}}{txt}{{\\c&HFFFFFF&}}" if j == wi else txt)
                ev.append(f"Dialogue: 0,{_ass_time(w_start - start)},{_ass_time(w_end - start)},"
                          f"Cap,,0,0,0,,{' '.join(parts)}")
    return header + "\n".join(ev) + "\n"


# ---------------------------------------------------------------- ffmpeg
def _filter(layout: str, facecam: list[float] | None) -> str:
    bg = f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=28,eq=brightness=-0.08[bg]"
    if layout == "split" and facecam:
        fx, fy, fw, fh = facecam
        top_h, bot_h = 768, H - 768
        return (f"[0:v]split=2[a][b];"
                f"[a]crop=iw*{fw}:ih*{fh}:iw*{fx}:ih*{fy},scale={W}:{top_h}:force_original_aspect_ratio=increase,crop={W}:{top_h}[top];"
                f"[b]crop=ih*{W}/{bot_h}:ih,scale={W}:{bot_h}[bot];"
                f"[top][bot]vstack,subtitles=captions.ass[v]")
    if layout == "zoom":
        fg = f"[0:v]crop=ih*1.0:ih,scale={W}:{W}[fg]"
    else:
        fg = f"[0:v]scale={W}:-2[fg]"
    return f"{bg};{fg};[bg][fg]overlay=(W-w)/2:(H-h)/2,subtitles=captions.ass[v]"


def render_clip(cand: dict, pick: dict, clip_id: str, words: list[dict]) -> dict:
    cfg = load_config()
    rc = cfg.get("render", {})
    start, end = float(pick["start"]), float(pick["end"])
    src, base = fetch_source(cand, start, end)

    ch = rights.find_channel(cand.get("platform", ""), cand.get("channel_id"), cand.get("channel"))
    layout = (ch or {}).get("layout") or rc.get("layout", "blurpad")
    facecam = (ch or {}).get("facecam")
    if layout == "split" and not facecam:
        layout = "blurpad"

    work = WORK_DIR / "render" / clip_id
    work.mkdir(parents=True, exist_ok=True)
    credit = rc.get("credit_template", "via {channel}").format(channel=cand.get("channel") or "source") \
        if cand.get("channel") else ""
    (work / "captions.ass").write_text(
        build_ass(words, start, end, pick.get("hook", ""), credit, layout, rc), encoding="utf-8")

    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    out = CLIPS_DIR / f"{clip_id}.mp4"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{max(start - base, 0):.3f}", "-t", f"{end - start:.3f}", "-i", str(src.resolve()),
           "-filter_complex", _filter(layout, facecam), "-map", "[v]", "-map", "0:a?",
           "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-r", "30",
           "-c:v", "libx264", "-preset", rc.get("x264_preset", "veryfast"), "-crf", str(rc.get("crf", 20)),
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
           "-movflags", "+faststart", str(out.resolve())]
    proc = run(cmd, timeout=900, cwd=work)
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError("ffmpeg: " + proc.stderr.strip()[-400:])
    qc = run_qc(out, clip_id, expected=end - start)
    rel = lambda p: str(Path(p).resolve().relative_to(ROOT.resolve())) if p else None  # noqa: E731
    return {"file": rel(out), "thumb": rel(qc.pop("thumb", None)), "grid": rel(qc.pop("grid", None)),
            "qc": qc, "layout": layout}


# ---------------------------------------------------------------- QC
def probe(path: Path) -> dict:
    proc = run(["ffprobe", "-v", "error", "-show_entries",
                "format=duration:stream=codec_type,width,height", "-of", "json", str(path)], timeout=60)
    d = json.loads(proc.stdout or "{}")
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    return {"duration": round(float(d.get("format", {}).get("duration", 0)), 2),
            "width": v.get("width"), "height": v.get("height"),
            "has_audio": any(s.get("codec_type") == "audio" for s in d.get("streams", []))}


def run_qc(path: Path, clip_id: str, expected: float) -> dict:
    p = probe(path)
    issues = []
    if (p["width"], p["height"]) != (W, H):
        issues.append(f"resolution {p['width']}x{p['height']}")
    if abs(p["duration"] - expected) > 1.5:
        issues.append(f"duration {p['duration']}s vs {expected:.1f}s")
    if not p["has_audio"]:
        issues.append("no audio")
    else:
        vol = run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"], timeout=120)
        m = re.search(r"mean_volume: (-?[\d.]+) dB", vol.stderr)
        p["mean_volume_db"] = float(m.group(1)) if m else None
        if m and float(m.group(1)) < -40:
            issues.append("near-silent audio")
    blk = run(["ffmpeg", "-hide_banner", "-i", str(path), "-vf", "blackdetect=d=0.5:pix_th=0.10",
               "-an", "-f", "null", "-"], timeout=180)
    black = sum(float(x) for x in re.findall(r"black_duration:([\d.]+)", blk.stderr))
    p["black_seconds"] = round(black, 1)
    if p["duration"] and black / p["duration"] > 0.3:
        issues.append(f"{black:.0f}s black frames")

    thumb = CLIPS_DIR / f"{clip_id}.jpg"
    grid = CLIPS_DIR / f"{clip_id}_grid.jpg"
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(min(1.5, p["duration"] / 2)), "-i", str(path),
         "-frames:v", "1", "-vf", "scale=360:-2", str(thumb)], timeout=60)
    step = max(p["duration"] / 6, 0.5)
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-vf",
         f"fps=1/{step:.3f},scale=270:480,tile=3x2", "-frames:v", "1", str(grid)], timeout=120)
    p["ok"] = not issues
    p["issues"] = issues
    p["thumb"] = str(thumb) if thumb.exists() else None
    p["grid"] = str(grid) if grid.exists() else None
    log(f"qc {clip_id}: {'OK' if not issues else issues}")
    return p

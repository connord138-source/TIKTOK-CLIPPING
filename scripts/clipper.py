#!/usr/bin/env python3
"""Streamer-clipping pipeline: VOD section -> transcript -> 9:16 captioned clip.

Validated recipe (docs/CAPABILITY-NOTES.md): blur-pad 9:16 composite, burned ASS
captions, loudnorm I=-14, h264/aac faststart. Media lives in work/<job>/ (gitignored);
only metadata goes in the repo.

Usage (typical session flow):
  clipper.py doctor                                   # tooling + network matrix
  clipper.py probe URL                                # duration/formats/subs
  clipper.py ingest URL --section 600-900 [--quality 720p] [--job name]
  clipper.py transcribe [--model small.en]            # subs if present, else whisper
  clipper.py moments [--top 8]                        # heuristic assist only —
                                                      # final pick is editorial
  clipper.py cut --start 41 --end 66 [--hook "TEXT"] [--out clip-001]
  clipper.py qc [--clip clip-001]                     # frame grid + probe + loudness
  clipper.py pack                                     # deliverables manifest

Times passed to cut/moments are seconds relative to the INGESTED file (section-local).
meta.json records the section's VOD offset for campaign reporting.
"""
import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORK = REPO / "work"
LAST_JOB_FILE = WORK / ".last-job"

QUALITY_MAP = {  # yt-dlp -f selectors; twitch uses named formats, youtube needs filters
    "720p": "720p/b[height<=720]/bv*[height<=720]+ba",
    "1080p": "1080p60/1080p/b[height<=1080]/bv*[height<=1080]+ba",
    "best": "b/bv*+ba",
    "audio": "Audio_Only/ba",
}

HYPE_WORDS = {
    "insane", "crazy", "unbelievable", "clutch", "unreal", "wild", "cooked",
    "cracked", "goated", "rigged", "actually", "literally", "no", "way",
    "what", "bro", "dude", "chat", "clip", "omg", "lmao", "lol", "gg",
    "win", "won", "lost", "dead", "died", "one", "shot", "world", "record",
}


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def die(msg: str) -> None:
    sys.exit(f"clipper: error: {msg}")


def run(cmd, cwd=None, capture=False, check=True, timeout=None):
    """Run a subprocess; on capture return (code, stdout+stderr)."""
    if capture:
        p = subprocess.run(cmd, cwd=cwd, timeout=timeout, text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if check and p.returncode != 0:
            die(f"command failed ({cmd[0]}):\n{p.stdout[-2000:]}")
        return p.returncode, p.stdout
    p = subprocess.run(cmd, cwd=cwd, timeout=timeout)
    if check and p.returncode != 0:
        die(f"command failed: {' '.join(map(str, cmd))}")
    return p.returncode, ""


def fmt_ts(seconds: float) -> str:
    seconds = max(0, seconds)
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ---------------------------------------------------------------- job handling

def job_dir(name: str | None, create: bool = False) -> Path:
    WORK.mkdir(exist_ok=True)
    if name is None:
        if not LAST_JOB_FILE.exists():
            die("no job yet — run ingest first, or pass --job")
        name = LAST_JOB_FILE.read_text().strip()
    d = WORK / name
    if create:
        d.mkdir(parents=True, exist_ok=True)
        LAST_JOB_FILE.write_text(name + "\n")
    elif not d.exists():
        die(f"job dir not found: {d}")
    return d


def load_meta(job: Path) -> dict:
    f = job / "meta.json"
    return json.loads(f.read_text()) if f.exists() else {}


def save_meta(job: Path, meta: dict) -> None:
    (job / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")


# --------------------------------------------------------------------- doctor

DOCTOR_HOSTS = [
    "www.twitch.tv", "kick.com", "www.youtube.com", "drive.google.com",
    "www.dropbox.com", "whop.com", "huggingface.co", "archive.org",
]


def cmd_doctor(_args) -> None:
    for tool in ("ffmpeg", "ffprobe", "yt-dlp"):
        path = shutil.which(tool)
        print(f"{tool:<12} {'OK  ' + path if path else 'MISSING — apt/pip install'}")
    try:
        import faster_whisper  # noqa: F401
        print(f"{'whisper':<12} OK  faster-whisper importable")
    except ImportError:
        print(f"{'whisper':<12} MISSING — pip3 install faster-whisper")
    code, out = run(["fc-list"], capture=True, check=False)
    n = out.lower().count("dejavu")
    print(f"{'fonts':<12} {'OK  DejaVu x' + str(n) if n else 'MISSING DejaVu (fonts-dejavu)'}")
    print("network:")
    for host in DOCTOR_HOSTS:
        code, out = run(
            ["curl", "-s", "-o", "/dev/null", "-m", "10", "-w", "%{http_code}",
             f"https://{host}/"], capture=True, check=False)
        status = out.strip() or "000"
        verdict = "open" if status not in ("000",) else "BLOCKED"
        print(f"  {host:<28} {status}  {verdict}")


# ---------------------------------------------------------------------- probe

def cmd_probe(args) -> None:
    code, out = run(["yt-dlp", "--no-warnings", "-J", "--skip-download", args.url],
                    capture=True)
    data = json.loads(out[out.index("{"):])
    subs = sorted(set(list((data.get("subtitles") or {}).keys())
                      + list((data.get("automatic_captions") or {}).keys())))
    heights = sorted({f.get("height") for f in data.get("formats", [])
                      if f.get("height")})
    print(json.dumps({
        "id": data.get("id"),
        "title": data.get("title"),
        "uploader": data.get("uploader") or data.get("channel"),
        "duration_s": data.get("duration"),
        "duration": fmt_ts(data.get("duration") or 0),
        "heights": heights,
        "subs_langs": [s for s in subs if s.startswith("en")][:6],
        "webpage_url": data.get("webpage_url"),
    }, indent=2))


# --------------------------------------------------------------------- ingest

def parse_section(spec: str) -> tuple[float, float]:
    m = re.fullmatch(r"([\d.:]+)-([\d.:]+)", spec)
    if not m:
        die(f"bad --section {spec!r}; want START-END in seconds or H:MM:SS")

    def to_s(t: str) -> float:
        if ":" in t:
            parts = [float(p) for p in t.split(":")]
            return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))
        return float(t)

    start, end = to_s(m.group(1)), to_s(m.group(2))
    if end <= start:
        die("--section end must be after start")
    return start, end


def slugify(text: str, maxlen: int = 24) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "clip").lower()).strip("-")
    return slug[:maxlen] or "clip"


def cmd_ingest(args) -> None:
    is_url = re.match(r"https?://", args.source)
    direct = is_url and re.search(r"\.(mp4|mkv|webm|mov|m4v)(\?|$)", args.source)
    section = parse_section(args.section) if args.section else None

    title, uploader, vod_id, duration = None, None, None, None
    if is_url and not direct:
        code, out = run(["yt-dlp", "--no-warnings", "--print",
                         "%(id)s\t%(title)s\t%(uploader,channel)s\t%(duration)s",
                         "--skip-download", args.source], capture=True)
        line = [l for l in out.strip().splitlines() if "\t" in l][-1]
        vod_id, title, uploader, dur_s = (line.split("\t") + [None] * 4)[:4]
        duration = float(dur_s) if dur_s and dur_s != "NA" else None
        if section and duration and section[0] >= duration:
            die(f"section starts at {fmt_ts(section[0])} but VOD is only "
                f"{fmt_ts(duration)} long")

    name = args.job or "j-{}-{}".format(
        datetime.now(timezone.utc).strftime("%m%d-%H%M"), slugify(title or "src"))
    job = job_dir(name, create=True)
    src = job / "source.mp4"

    if not is_url:  # local file
        local = Path(args.source).expanduser().resolve()
        if not local.exists():
            die(f"local file not found: {local}")
        if section:
            run(["ffmpeg", "-y", "-v", "error", "-ss", str(section[0]),
                 "-t", str(section[1] - section[0]), "-i", str(local),
                 "-c", "copy", str(src)])
        else:
            shutil.copy2(local, src)
    elif direct:  # plain media URL: validated remote range-seek
        cmd = ["ffmpeg", "-y", "-v", "error"]
        if section:
            cmd += ["-ss", str(section[0]), "-t", str(section[1] - section[0])]
        cmd += ["-i", args.source, "-c", "copy", "-movflags", "+faststart", str(src)]
        run(cmd)
    else:  # platform URL via yt-dlp
        cmd = ["yt-dlp", "--no-warnings", "-f", QUALITY_MAP[args.quality],
               "-o", "source.%(ext)s", "--downloader-args", "ffmpeg:-v error", "--write-auto-subs", "--write-subs",
               "--sub-langs", "en.*,en", "--sub-format", "vtt"]
        if section:
            cmd += ["--download-sections", f"*{section[0]}-{section[1]}"]
        run(cmd + [args.source], cwd=job)
        produced = sorted(job.glob("source.*"))
        media = [p for p in produced if p.suffix in (".mp4", ".mkv", ".webm")]
        if not media:
            die("yt-dlp produced no media file (see output above)")
        if media[0] != src:
            media[0].rename(src) if media[0].suffix == ".mp4" else run(
                ["ffmpeg", "-y", "-v", "error", "-i", str(media[0]),
                 "-c", "copy", str(src)])

    code, out = run(["ffprobe", "-v", "error", "-show_entries",
                     "format=duration", "-of", "csv=p=0", str(src)], capture=True)
    got_dur = float(out.strip().splitlines()[-1])

    meta = {
        "job": name, "source_url": args.source if is_url else str(args.source),
        "vod_id": vod_id, "title": title, "uploader": uploader,
        "vod_duration_s": duration,
        "section_start_s": section[0] if section else 0.0,
        "section_end_s": section[1] if section else got_dur,
        "ingested_duration_s": round(got_dur, 2),
        "quality": args.quality, "ingested_at": now_utc(),
        "campaign": args.campaign,
    }
    save_meta(job, meta)
    subs = sorted(job.glob("source.*.vtt"))
    print(f"job {name}: {fmt_ts(got_dur)} ingested"
          + (f" (VOD offset {fmt_ts(meta['section_start_s'])})" if section else "")
          + (f", subs: {subs[0].name}" if subs else ", no platform subs"))


# ----------------------------------------------------------------- transcribe

def parse_vtt_words(vtt_text: str) -> list[dict]:
    """YouTube auto-sub VTT -> [{'w','s','e'}], deduping roll-up repeats."""
    words, seen = [], set()
    ts = r"(\d+):(\d{2}):(\d{2})\.(\d{3})"

    def to_s(m):
        h, mnt, s, ms = (int(g) for g in m.groups())
        return h * 3600 + mnt * 60 + s + ms / 1000

    for block in vtt_text.split("\n\n"):
        head = re.search(ts + r" --> " + ts, block)
        if not head:
            continue
        cue_start = to_s(re.match(ts, head.group(0)))
        for text_line in block.splitlines()[1:]:
            if "-->" in text_line or not text_line.strip():
                continue
            tagged = re.findall(r"<" + ts + r"><c>([^<]*)</c>", text_line)
            if tagged:
                first_plain = re.match(r"^([^<]+)", text_line)
                if first_plain and (round(cue_start, 2), first_plain.group(1).strip()) not in seen:
                    tok = first_plain.group(1).strip()
                    if tok:
                        seen.add((round(cue_start, 2), tok))
                        words.append({"w": tok, "s": cue_start, "e": cue_start})
                for h, mnt, s, ms, tok in tagged:
                    t = int(h) * 3600 + int(mnt) * 60 + int(s) + int(ms) / 1000
                    tok = tok.strip()
                    if tok and (round(t, 2), tok) not in seen:
                        seen.add((round(t, 2), tok))
                        words.append({"w": tok, "s": t, "e": t})
    words.sort(key=lambda w: w["s"])
    for i, w in enumerate(words):  # give each word an end time
        w["e"] = words[i + 1]["s"] if i + 1 < len(words) else w["s"] + 0.4
    return words


def words_to_segments(words: list[dict], gap: float = 0.9, max_words: int = 14) -> list[dict]:
    segs, cur = [], []
    for w in words:
        if cur and (w["s"] - cur[-1]["e"] > gap or len(cur) >= max_words):
            segs.append(cur)
            cur = []
        cur.append(w)
    if cur:
        segs.append(cur)
    return [{"start": round(c[0]["s"], 2), "end": round(c[-1]["e"], 2),
             "text": " ".join(w["w"] for w in c),
             "words": [{"w": w["w"], "s": round(w["s"], 2), "e": round(w["e"], 2)}
                       for w in c]} for c in segs]


def cmd_transcribe(args) -> None:
    job = job_dir(args.job)
    meta = load_meta(job)
    vtts = sorted(job.glob("source.en*.vtt")) or sorted(job.glob("source.*.vtt"))

    if vtts and not args.force_whisper:
        words = parse_vtt_words(vtts[0].read_text(errors="replace"))
        if len(words) < 5:
            print("platform subs too sparse — falling back to whisper")
            segs = whisper_transcribe(job, args.model)
        else:
            segs = words_to_segments(words)
            print(f"transcript from platform subs: {vtts[0].name}")
    else:
        segs = whisper_transcribe(job, args.model)

    (job / "transcript.json").write_text(json.dumps(segs, indent=1) + "\n")
    offset = meta.get("section_start_s", 0)
    lines = [f"# {meta.get('title', '?')} — section-local times "
             f"(add {fmt_ts(offset)} for VOD position)"]
    lines += [f"[{fmt_ts(s['start'])}] {s['text']}" for s in segs]
    (job / "transcript.txt").write_text("\n".join(lines) + "\n")
    n_words = sum(len(s["words"]) for s in segs)
    print(f"{len(segs)} segments, {n_words} words -> transcript.json / transcript.txt")


def whisper_transcribe(job: Path, model_name: str) -> list[dict]:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        die("faster-whisper not installed: pip3 install faster-whisper")
    print(f"whisper {model_name} (cpu int8) ...")
    model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=4)
    segments, _info = model.transcribe(str(job / "source.mp4"),
                                       vad_filter=True, word_timestamps=True)
    segs = []
    for s in segments:
        segs.append({"start": round(s.start, 2), "end": round(s.end, 2),
                     "text": s.text.strip(),
                     "words": [{"w": w.word.strip(), "s": round(w.start, 2),
                                "e": round(w.end, 2)} for w in (s.words or [])]})
    return segs


# -------------------------------------------------------------------- moments

def cmd_moments(args) -> None:
    job = job_dir(args.job)
    segs = json.loads((job / "transcript.json").read_text())
    if not segs:
        die("empty transcript")
    win, hop = args.window, args.window / 2
    end_t = segs[-1]["end"]
    scored = []
    t = 0.0
    while t < end_t:
        w_end = t + win
        text = " ".join(s["text"] for s in segs if s["start"] < w_end and s["end"] > t)
        toks = re.findall(r"[a-z']+", text.lower())
        if toks:
            hype = sum(1 for tok in toks if tok in HYPE_WORDS)
            excl = text.count("!") + text.count("?")
            caps = len(re.findall(r"\b[A-Z]{2,}\b", text))
            density = len(toks) / win
            score = hype * 2 + excl * 1.5 + caps + density
            scored.append((round(score, 1), t, min(w_end, end_t), text))
        t += hop
    scored.sort(reverse=True)
    print(f"heuristic assist — top {args.top} windows of {win:.0f}s "
          "(EDITORIAL PICK STILL REQUIRED — read transcript.txt):")
    for score, s, e, text in scored[:args.top]:
        print(f"  {score:>6}  {fmt_ts(s)}-{fmt_ts(e)}  {text[:90]}")


# ------------------------------------------------------------------------ cut

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,DejaVu Sans,64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,0,2,60,60,430,1
Style: Hook,DejaVu Sans,68,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,0,8,60,60,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

ACCENT = r"{\c&H0000FFFF&}"   # yellow (ASS is BGR)
WHITE = r"{\c&HFFFFFF&}"


def ass_time(t: float) -> str:
    t = max(0, t)
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def ass_escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\n", r"\N")


def build_ass(words: list[dict], clip_start: float, clip_end: float,
              hook: str | None, max_card_words: int = 4,
              max_card_span: float = 1.8) -> str:
    """Group words into short caption cards, accent-color the loudest word."""
    events = []
    if hook:
        events.append(f"Dialogue: 0,{ass_time(0)},{ass_time(min(4.5, clip_end - clip_start))},"
                      f"Hook,,0,0,0,,{ass_escape(hook.upper())}")
    card: list[dict] = []

    def flush(card):
        if not card:
            return
        start = card[0]["s"] - clip_start
        end = max(card[-1]["e"] - clip_start, start + 0.35)
        parts = []
        accent_i = max(range(len(card)),
                       key=lambda i: (card[i]["w"].isupper() and len(card[i]["w"]) > 1,
                                      card[i]["w"].lower().strip(",.!?") in HYPE_WORDS,
                                      len(card[i]["w"])))
        for i, w in enumerate(card):
            tok = ass_escape(w["w"])
            parts.append(f"{ACCENT}{tok}{WHITE}" if i == accent_i else tok)
        text = r"{\fad(60,30)}" + " ".join(parts)
        events.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},"
                      f"Caption,,0,0,0,,{text}")

    for w in words:
        if w["e"] < clip_start or w["s"] > clip_end:
            continue
        if card and (len(card) >= max_card_words
                     or w["e"] - card[0]["s"] > max_card_span
                     or re.search(r"[.!?]$", card[-1]["w"])):
            flush(card)
            card = []
        card.append(w)
    flush(card)
    return ASS_HEADER + "\n".join(events) + "\n"


def cmd_cut(args) -> None:
    job = job_dir(args.job)
    meta = load_meta(job)
    src = job / "source.mp4"
    if not src.exists():
        die("no source.mp4 — run ingest first")
    length = args.end - args.start
    if length <= 3:
        die("clip must be longer than 3s")
    if length > 180:
        die("clip longer than 180s — split it")

    out_name = args.out or f"clip-{len(list(job.glob('clip-*.mp4'))) + 1:03d}"
    out = job / f"{out_name}.mp4"

    filters = ["[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
               "crop=1080:1920,gblur=sigma=24[bg]",
               "[0:v]scale=1080:-2[fg]",
               "[bg][fg]overlay=(W-w)/2:(H-h)/2[comp]"]
    last = "comp"
    if not args.no_captions:
        tfile = job / "transcript.json"
        if not tfile.exists():
            die("no transcript.json — run transcribe first (or pass --no-captions)")
        segs = json.loads(tfile.read_text())
        words = [w for s in segs for w in s["words"]]
        ass = build_ass(words, args.start, args.end, args.hook)
        (job / f"{out_name}.ass").write_text(ass)
        filters.append(f"[comp]subtitles={out_name}.ass[v]")
        last = "v"
    elif args.hook:
        ass = build_ass([], args.start, args.end, args.hook)
        (job / f"{out_name}.ass").write_text(ass)
        filters.append(f"[comp]subtitles={out_name}.ass[v]")
        last = "v"

    cmd = ["ffmpeg", "-y", "-v", "error", "-stats",
           "-ss", str(args.start), "-t", str(length), "-i", "source.mp4",
           "-filter_complex", ";".join(filters),
           "-map", f"[{last}]", "-map", "0:a?",
           "-af", "loudnorm=I=-14:TP=-1",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
           "-movflags", "+faststart", f"{out_name}.mp4"]
    run(cmd, cwd=job)

    clips = meta.setdefault("clips", [])
    clips = [c for c in clips if c["file"] != out.name]
    vod_off = meta.get("section_start_s", 0)
    clips.append({
        "file": out.name, "start_s": args.start, "end_s": args.end,
        "vod_start": fmt_ts(vod_off + args.start),
        "vod_end": fmt_ts(vod_off + args.end),
        "hook": args.hook, "rendered_at": now_utc(),
    })
    meta["clips"] = clips
    save_meta(job, meta)
    size_mb = out.stat().st_size / 1e6
    print(f"{out.name}: {length:.0f}s, {size_mb:.1f}MB "
          f"(VOD {fmt_ts(vod_off + args.start)}-{fmt_ts(vod_off + args.end)})")


# ------------------------------------------------------------------------- qc

def cmd_qc(args) -> None:
    job = job_dir(args.job)
    clip_name = args.clip or sorted(p.stem for p in job.glob("clip-*.mp4"))[-1:]
    if not clip_name:
        die("no clips rendered yet")
    clip_name = clip_name if isinstance(clip_name, str) else clip_name[0]
    clip = job / f"{clip_name}.mp4"
    if not clip.exists():
        die(f"not found: {clip}")

    code, out = run(["ffprobe", "-v", "error", "-show_entries",
                     "format=duration,size:stream=codec_name,width,height,r_frame_rate",
                     "-of", "json", str(clip)], capture=True)
    info = json.loads(out[out.index("{"):])
    dur = float(info["format"]["duration"])

    grid = job / f"{clip_name}-grid.jpg"
    tiles = 6
    interval = max(dur / tiles, 0.001)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(clip),
         "-vf", f"fps=1/{interval:.3f},scale=270:480,tile=3x2",
         "-frames:v", "1", "-q:v", "3", str(grid)], check=False)

    code, loud = run(["ffmpeg", "-i", str(clip), "-af",
                      "ebur128=framelog=quiet", "-f", "null", "-"],
                     capture=True, check=False)
    m = re.search(r"I:\s*(-?[\d.]+)\s*LUFS", loud)

    streams = {s["codec_name"]: s for s in info["streams"]}
    v = next((s for s in info["streams"] if "width" in s), {})
    print(f"{clip.name}: {dur:.1f}s, {int(info['format']['size']) / 1e6:.1f}MB, "
          f"{v.get('width')}x{v.get('height')}, "
          f"codecs {'+'.join(streams)}, "
          f"loudness {m.group(1) + ' LUFS' if m else '?'}")
    print(f"frame grid -> {grid}  (READ THIS IMAGE before delivering)")
    ass = job / f"{clip_name}.ass"
    if ass.exists():
        cards = re.findall(r"Caption,,0,0,0,,(?:\{[^}]*\})?(.+)", ass.read_text())
        plain = [re.sub(r"\{[^}]*\}", "", c) for c in cards]
        print(f"caption cards: {len(plain)}; first/last: "
              f"{plain[0][:40]!r} / {plain[-1][:40]!r}" if plain else "no caption cards")


# ----------------------------------------------------------------------- pack

def cmd_pack(args) -> None:
    job = job_dir(args.job)
    meta = load_meta(job)
    clips = meta.get("clips", [])
    if not clips:
        die("no clips in meta — run cut first")
    lines = [f"# Deliverables — {meta.get('title', job.name)}",
             f"source: {meta.get('source_url')}",
             f"campaign: {meta.get('campaign') or 'NOT SET — set before posting'}",
             ""]
    for c in clips:
        f = job / c["file"]
        if not f.exists():
            continue
        lines.append(f"{c['file']}  ({c['end_s'] - c['start_s']:.0f}s, "
                     f"VOD {c['vod_start']}-{c['vod_end']})")
        lines.append(f"  hook: {c.get('hook') or '(none burned)'}")
    lines += ["", "REMINDERS: AI-label ON if any AI edit visible; draft/file only —",
              "user posts; campaign-authorized material only."]
    manifest = job / "deliverables.txt"
    manifest.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nmanifest -> {manifest}")


# ----------------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check tooling + network matrix").set_defaults(
        func=cmd_doctor)

    p = sub.add_parser("probe", help="inspect a VOD url")
    p.add_argument("url")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("ingest", help="download source (section) into a job dir")
    p.add_argument("source", help="platform URL, direct media URL, or local path")
    p.add_argument("--section", help="START-END (secs or H:MM:SS), VOD-absolute")
    p.add_argument("--quality", choices=QUALITY_MAP, default="720p")
    p.add_argument("--job", help="job name (default: auto)")
    p.add_argument("--campaign", help="campaign id/name for the ledger")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("transcribe", help="platform subs else faster-whisper")
    p.add_argument("--job")
    p.add_argument("--model", default="small.en")
    p.add_argument("--force-whisper", action="store_true")
    p.set_defaults(func=cmd_transcribe)

    p = sub.add_parser("moments", help="heuristic hot-window assist (not a decision)")
    p.add_argument("--job")
    p.add_argument("--top", type=int, default=8)
    p.add_argument("--window", type=float, default=30.0)
    p.set_defaults(func=cmd_moments)

    p = sub.add_parser("cut", help="render 9:16 captioned clip from source")
    p.add_argument("--job")
    p.add_argument("--start", type=float, required=True, help="secs, section-local")
    p.add_argument("--end", type=float, required=True)
    p.add_argument("--hook", help="top-of-frame hook text")
    p.add_argument("--out", help="output stem (default clip-NNN)")
    p.add_argument("--no-captions", action="store_true")
    p.set_defaults(func=cmd_cut)

    p = sub.add_parser("qc", help="frame grid + probe + loudness")
    p.add_argument("--job")
    p.add_argument("--clip", help="clip stem, default latest")
    p.set_defaults(func=cmd_qc)

    p = sub.add_parser("pack", help="write deliverables manifest")
    p.add_argument("--job")
    p.set_defaults(func=cmd_pack)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

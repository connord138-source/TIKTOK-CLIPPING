"""Shared plumbing: paths, config, JSON store (atomic + locked), logging, time utils."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("CLIPFARM_ROOT", Path(__file__).resolve().parent.parent))
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
MEDIA_DIR = ROOT / "media"            # gitignored: sources, clips, thumbs, grids
WORK_DIR = MEDIA_DIR / "work"
CLIPS_DIR = MEDIA_DIR / "clips"
SECRETS_DIR = DATA_DIR / "secrets"    # gitignored: OAuth tokens

_lock = threading.RLock()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def hours_since(value: str | None) -> float | None:
    dt = parse_iso(value)
    if not dt:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)


_job_ctx = threading.local()  # pipeline jobs capture their own log lines here


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    sink = getattr(_job_ctx, "lines", None)
    if sink is not None:
        sink.append(line)
        del sink[:-300]


# ---------------------------------------------------------------- JSON store
@contextmanager
def _file_lock(path: Path, timeout: float = 15.0):
    """Cross-process lock (server + CLI may run at once). Portable: O_EXCL lockfile."""
    lockfile = path.with_suffix(path.suffix + ".lock")
    deadline = time.time() + timeout
    fd = None
    while fd is None:
        try:
            fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:  # stale lock (crashed writer) -> break it
                if time.time() - lockfile.stat().st_mtime > 60:
                    lockfile.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.time() > deadline:
                raise TimeoutError(f"lock busy: {lockfile}")
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(fd)
        lockfile.unlink(missing_ok=True)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        log(f"WARN corrupt json at {path}; using default")
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for attempt in range(8):  # Windows: replace fails while another thread has the file open
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.05 * (attempt + 1))


@contextmanager
def mutate(path: Path, default):
    """Read-modify-write a JSON file under thread + process locks."""
    with _lock, _file_lock(path):
        data = read_json(path, default)
        yield data
        write_json(path, data)


class Store:
    """Thin collection helpers over data/*.json."""

    clips = DATA_DIR / "clips.json"
    candidates = DATA_DIR / "candidates.json"
    metrics = DATA_DIR / "metrics.json"
    jobs = DATA_DIR / "jobs.json"

    @staticmethod
    def all(path: Path) -> list:
        with _lock:
            return read_json(path, [])

    @staticmethod
    def get(path: Path, item_id: str) -> dict | None:
        return next((x for x in Store.all(path) if x.get("id") == item_id), None)

    @staticmethod
    def upsert(path: Path, item: dict) -> dict:
        with mutate(path, []) as items:
            for i, existing in enumerate(items):
                if existing.get("id") == item["id"]:
                    merged = {**existing, **item, "updated_at": now_iso()}
                    items[i] = merged
                    return merged
            item.setdefault("created_at", now_iso())
            item["updated_at"] = now_iso()
            items.append(item)
            return item

    @staticmethod
    def update(path: Path, item_id: str, **fields) -> dict | None:
        with mutate(path, []) as items:
            for item in items:
                if item.get("id") == item_id:
                    item.update(fields)
                    item["updated_at"] = now_iso()
                    return dict(item)
        return None

    @staticmethod
    def reserve_clip(**fields) -> str:
        """Atomically allocate the next clip id (c0001, c0002, ...) and insert a stub."""
        with mutate(Store.clips, []) as items:
            nums = [int(c["id"][1:]) for c in items if c["id"][1:].isdigit()]
            cid = f"c{(max(nums, default=0) + 1):04d}"
            items.append({"id": cid, **fields, "created_at": now_iso(), "updated_at": now_iso()})
            return cid


# ---------------------------------------------------------------- config
def load_config() -> dict:
    return read_json(CONFIG_DIR / "account.json", {})


def save_config(cfg: dict) -> None:
    with _lock:
        write_json(CONFIG_DIR / "account.json", cfg)


def load_sources() -> dict:
    return read_json(CONFIG_DIR / "sources.json", {"policy": {}, "channels": [], "campaigns": []})


def save_sources(src: dict) -> None:
    with _lock:
        write_json(CONFIG_DIR / "sources.json", src)


def deep_merge(base: dict, patch: dict) -> dict:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
    return base


# ---------------------------------------------------------------- subprocess helpers
def ytdlp_cmd() -> list[str]:
    """yt-dlp via the current interpreter; enable node as JS runtime if deno is absent
    (YouTube extraction needs a JS runtime as of late 2025)."""
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings", "--ignore-config"]
    if not shutil.which("deno") and shutil.which("node"):
        cmd += ["--js-runtimes", "node"]
    cookies = load_config().get("ingest", {}).get("cookies_from_browser")
    if cookies:  # residential-IP bot checks: reuse the user's logged-in browser session
        cmd += ["--cookies-from-browser", cookies]
    return cmd


def run(cmd: list[str], timeout: int = 600, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)


def run_json(cmd: list[str], timeout: int = 180):
    proc = run(cmd, timeout=timeout)
    out = proc.stdout.strip()
    if not out or out == "null":
        raise RuntimeError((proc.stderr or "no output").strip().splitlines()[-1][:300])
    return json.loads(out[out.index("{"):] if not out.startswith(("{", "[")) else out)


def ensure_dirs() -> None:
    for d in (DATA_DIR, MEDIA_DIR, WORK_DIR, CLIPS_DIR, SECRETS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    load_keys()


# ---------------------------------------------------------------- keys saved from the dashboard
# Stored in data/secrets/keys.json (gitignored) and copied into the process environment, so
# the rest of the code keeps reading os.environ. Values are never sent back to the browser.
KEYS_FILE = SECRETS_DIR / "keys.json"
KEY_NAMES = ["ANTHROPIC_API_KEY", "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET",
             "TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET"]


def load_keys() -> None:
    for name, value in read_json(KEYS_FILE, {}).items():
        if name in KEY_NAMES and value:
            os.environ[name] = value


def save_keys(patch: dict) -> None:
    """Set (non-empty string) or clear (empty string) keys. Unknown names are rejected."""
    with _lock:
        keys = read_json(KEYS_FILE, {})
        for name, value in patch.items():
            if name not in KEY_NAMES:
                raise ValueError(f"unknown key name: {name}")
            value = (value or "").strip()
            if value:
                keys[name] = value
                os.environ[name] = value
            else:
                keys.pop(name, None)
                os.environ.pop(name, None)
        write_json(KEYS_FILE, keys)


def keys_status() -> dict:
    saved = read_json(KEYS_FILE, {})
    return {name: {"set": bool(os.environ.get(name)),
                   "source": "dashboard" if saved.get(name) else ("environment" if os.environ.get(name) else None),
                   "hint": ("…" + os.environ[name][-4:]) if len(os.environ.get(name, "")) >= 12 else None}
            for name in KEY_NAMES}

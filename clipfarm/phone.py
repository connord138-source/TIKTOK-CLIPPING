"""Phone page: today's clips with their captions, readable from the user's phone on the same
Wi-Fi. TikTok's draft upload cannot carry a caption, so this is how the caption gets to the
phone: scan the QR code on the dashboard once, then tap "Copy caption" before posting.

Security: the dashboard itself stays local-only. A device that is not this computer can only
open the phone page and the clip files it links to, only while the user has the phone page
switched on, and only with the secret key that is inside the QR code.
"""
from __future__ import annotations

import html
import re
import secrets
import socket

from . import planner
from .core import SECRETS_DIR, Store, load_config

TOKEN_FILE = SECRETS_DIR / "phone_key.txt"
MEDIA_OK = re.compile(r"/media/clips/c\d+\.(jpg|mp4)")


def enabled() -> bool:
    return bool(load_config().get("phone", {}).get("enabled"))


def token() -> str:
    if TOKEN_FILE.exists():
        t = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if t:
            return t
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    t = secrets.token_urlsafe(9)
    TOKEN_FILE.write_text(t, encoding="utf-8")
    return t


def lan_ip() -> str | None:
    """This computer's address on the home network (no packets are sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except OSError:
        ip = None
    finally:
        s.close()
    return ip if ip and not ip.startswith("127.") else None


def info(port: int) -> dict:
    ip = lan_ip()
    return {"enabled": enabled(), "lan_ip": ip,
            "url": f"http://{ip}:{port}/phone?k={token()}" if ip else None}


def is_local(client_ip: str) -> bool:
    return client_ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1")


def lan_allowed(path: str, key: str | None) -> bool:
    """May a device other than this computer GET this path?"""
    if not enabled() or not key or not secrets.compare_digest(key, token()):
        return False
    return path == "/phone" or bool(MEDIA_OK.fullmatch(path))


def clips_for_phone() -> list[dict]:
    p = planner.plan()
    slot_of = {b["clip_id"]: b["time"] for b in p["slots"] if b.get("clip_id")}
    rank = {"drafted": 0, "approved": 1}
    clips = [c for c in Store.all(Store.clips) if c.get("status") in rank]
    clips.sort(key=lambda c: (rank[c["status"]], slot_of.get(c["id"], "99:99"), c["id"]))
    return [{**c, "slot": slot_of.get(c["id"])} for c in clips]


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Clipfarm captions</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin: 0; padding: 16px; background: #0f0d14; color: #f2eff7; font: 16px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  p.sub {{ color: #a59fb5; margin: 0 0 16px; font-size: 14px; }}
  .clip {{ background: #17141f; border: 1px solid #2e2840; border-radius: 14px; padding: 14px; margin-bottom: 14px; }}
  .top {{ display: flex; gap: 12px; align-items: flex-start; }}
  .top img {{ width: 72px; aspect-ratio: 9/16; object-fit: cover; border-radius: 8px; background: #000; flex: none; }}
  .hook {{ font-weight: 700; }}
  .meta {{ color: #a59fb5; font-size: 13px; margin-top: 4px; }}
  .tag {{ display: inline-block; font-size: 11px; font-weight: 700; letter-spacing: .4px; text-transform: uppercase; border: 1px solid currentColor; border-radius: 999px; padding: 1px 8px; }}
  .tag.d {{ color: #ff4f9a; }} .tag.a {{ color: #34c77b; }}
  textarea {{ width: 100%; box-sizing: border-box; margin-top: 12px; min-height: 96px; background: #201b2b; color: #f2eff7; border: 1px solid #2e2840; border-radius: 10px; padding: 10px; font: inherit; font-size: 15px; resize: vertical; }}
  .row {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }}
  button, a.btn {{ flex: 1; min-height: 48px; border-radius: 10px; border: 1px solid #2e2840; background: #201b2b; color: #f2eff7; font: inherit; font-weight: 700; text-align: center; text-decoration: none; display: inline-flex; align-items: center; justify-content: center; padding: 0 12px; }}
  button.primary {{ background: #ff4f9a; border-color: #ff4f9a; color: #1a0712; }}
  button.done {{ background: #34c77b; border-color: #34c77b; color: #04150c; }}
  .empty {{ border: 1px dashed #2e2840; border-radius: 14px; padding: 24px; text-align: center; color: #a59fb5; }}
</style>
</head>
<body>
<h1>Captions for today's clips</h1>
<p class="sub">Tap Copy caption, switch to TikTok, open the draft, paste, post. This page refreshes when you come back to it.</p>
{body}
<script>
  function copyCaption(id, btn) {{
    var t = document.getElementById(id);
    t.focus(); t.select(); t.setSelectionRange(0, 99999);
    var ok = false;
    try {{ ok = document.execCommand("copy"); }} catch (e) {{}}
    function done() {{ btn.textContent = "Copied"; btn.className = "done"; setTimeout(function () {{ btn.textContent = "Copy caption"; btn.className = "primary"; }}, 2500); }}
    if (ok) return done();
    if (navigator.clipboard) return navigator.clipboard.writeText(t.value).then(done, function () {{ btn.textContent = "Press and hold the text to copy"; }});
    btn.textContent = "Press and hold the text to copy";
  }}
  document.addEventListener("visibilitychange", function () {{ if (!document.hidden) location.reload(); }});
</script>
</body>
</html>
"""


def render_page(key: str) -> str:
    e = html.escape
    k = e(key, quote=True)
    parts = []
    for c in clips_for_phone():
        cid = e(c["id"])
        drafted = c["status"] == "drafted"
        tag = '<span class="tag d">in your TikTok drafts</span>' if drafted else '<span class="tag a">ready, not sent yet</span>'
        thumb = f'<img src="/media/clips/{cid}.jpg?k={k}" alt="">' if c.get("thumb") else ""
        slot = f"Post at {e(c['slot'])} · " if c.get("slot") else ""
        parts.append(
            f'<div class="clip"><div class="top">{thumb}<div><div class="hook">{e(c.get("hook") or cid)}</div>'
            f'<div class="meta">{slot}{e(str(c.get("duration") or ""))}s · {cid}</div><div style="margin-top:6px">{tag}</div></div></div>'
            f'<textarea id="cap-{cid}" readonly>{e(c.get("caption") or "")}</textarea>'
            f'<div class="row"><button class="primary" onclick="copyCaption(\'cap-{cid}\', this)">Copy caption</button>'
            + (f'<a class="btn" href="/media/clips/{cid}.mp4?k={k}" download="{cid}.mp4">Save video</a>' if c.get("file") else "")
            + "</div></div>")
    body = "\n".join(parts) or '<div class="empty">No clips are waiting right now. Approved clips and clips sent to your drafts show up here.</div>'
    return PAGE.format(body=body)

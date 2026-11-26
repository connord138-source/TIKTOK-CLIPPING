"""The "clips ready" email: one message per run when new clips land in the review queue or
come out approved, sent from the user's own Gmail to itself.

The subject always starts with SUBJECT, so a mail rule or another assistant can watch for it.
The body lists how many clips, and each clip's niche and account. It never contains a link,
an id or any code.

Set up by the user in the dashboard's Connections tab: the Gmail address and a Gmail app
password are stored with the other keys in data/secrets/keys.json (gitignored), and the
switch lives under `notify.email.enabled` in config.
"""
from __future__ import annotations

import os
import re
import smtplib
import ssl
from email.message import EmailMessage

from . import accounts, niches
from .core import Store, load_config, log, now_iso

SUBJECT = "[Clip Farm] Clips ready"
TEST_SUBJECT = "[Clip Farm] Test email"   # deliberately different: a test must not look like real clips
_last = {"sent_at": None, "error": None}


class NotifyError(RuntimeError):
    pass


def _settings() -> dict:
    return load_config().get("notify", {}).get("email", {})


def enabled() -> bool:
    return bool(_settings().get("enabled"))


def address() -> str | None:
    return (os.environ.get("NOTIFY_EMAIL") or "").strip() or None


def configured() -> bool:
    return bool(address() and os.environ.get("NOTIFY_EMAIL_PASSWORD"))


def status() -> dict:
    return {"enabled": enabled(), "configured": configured(), "subject": SUBJECT,
            "last_sent_at": _last["sent_at"], "last_error": _last["error"]}


# ---------------------------------------------------------------- sending
def _deliver(msg: EmailMessage) -> None:
    s = _settings()
    host, port = s.get("host", "smtp.gmail.com"), int(s.get("port", 465))
    password = (os.environ.get("NOTIFY_EMAIL_PASSWORD") or "").replace(" ", "")   # Google shows it in groups of four
    try:
        with smtplib.SMTP_SSL(host, port, timeout=30, context=ssl.create_default_context()) as smtp:
            smtp.login(address(), password)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise NotifyError("Gmail refused the sign-in. Use a Gmail app password (16 letters), not your normal "
                          "password, and check the address.") from None
    except smtplib.SMTPException as e:
        raise NotifyError(f"Gmail did not accept the email: {str(e)[:140]}") from None
    except OSError as e:
        raise NotifyError(f"Could not reach the mail server ({host}). Check the internet connection or a firewall "
                          f"blocking port {port}. ({type(e).__name__})") from None


def _send(subject: str, body: str) -> None:
    if not configured():
        raise NotifyError("Enter your Gmail address and app password first.")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = address()
    msg["To"] = address()
    msg.set_content(body)
    try:
        _deliver(msg)
    except NotifyError as e:
        _last["error"] = str(e)
        raise
    _last.update(sent_at=now_iso(), error=None)


def send_test() -> dict:
    _send(TEST_SUBJECT, "This is a test from your Clip Farm dashboard. Email is set up correctly.\n\n"
                        f"When new clips are ready you will get an email whose subject starts with:\n{SUBJECT}\n")
    return status()


# ---------------------------------------------------------------- the clips-ready email
def _plain(text: str) -> str:
    """Hooks come from Claude and from video titles: keep them to plain words, never a link."""
    text = re.sub(r"(https?://|www\.)\S+", "", text or "")
    return re.sub(r"\s+", " ", text).strip()[:90]


def _account_label(clip: dict) -> str:
    a = accounts.get(clip.get("account_id"))
    if a:
        return a.get("name") or "your account"
    fits = [x.get("name") or "account" for x in accounts.active() if accounts.takes(x, clip)]
    if len(fits) == 1:
        return fits[0]
    if fits:
        return "one of " + ", ".join(fits)
    return "no account set for this niche yet" if accounts.all_accounts() else "your account"


def compose(clips: list[dict]) -> tuple[str, str]:
    n = len(clips)
    review = sum(1 for c in clips if c.get("status") == "rendered")
    lines = [f"{n} new clip{'s are' if n != 1 else ' is'} ready in your Clip Farm dashboard.", ""]
    for c in clips:
        state = "waiting for your review" if c.get("status") == "rendered" else "approved and ready to post"
        title = _plain(c.get("hook") or "") or "Untitled clip"
        lines.append(f"- {title}\n  Niche: {niches.get(c.get('niche'))['name']} | Account: {_account_label(c)} | {state}")
    lines += ["", ("They are waiting in the Review tab of the dashboard on your PC." if review
                   else "They are waiting in the dashboard on your PC.")]
    return f"{SUBJECT}: {n} new", "\n".join(lines) + "\n"


def clips_ready(clip_ids: list[str]) -> dict:
    """Call once at the end of a run with every clip it made. Sends at most one email, and only
    for clips that reached the review queue or came out approved and were not announced before.
    Never raises: a mail problem must not fail a run."""
    try:
        if not clip_ids or not enabled() or not configured():
            return {"sent": False}
        wanted = set(clip_ids)
        from . import planner
        planner.plan()   # gives approved clips their account, so the email can name it
        fresh = [c for c in Store.all(Store.clips)
                 if c["id"] in wanted and c.get("status") in ("rendered", "approved") and not c.get("notified_at")]
        if not fresh:
            return {"sent": False}
        subject, body = compose(fresh)
        _send(subject, body)
        stamp = now_iso()
        for c in fresh:
            Store.update(Store.clips, c["id"], notified_at=stamp)
        log(f"email: told you about {len(fresh)} new clip(s)")
        return {"sent": True, "clips": len(fresh)}
    except Exception as e:  # noqa: BLE001
        _last["error"] = str(e)
        log(f"email: not sent: {e}")
        return {"sent": False, "error": str(e)}

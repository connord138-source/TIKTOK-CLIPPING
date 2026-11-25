import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from clipfarm import analytics, brain, moments, pipeline, planner, render, rights, server
from clipfarm.core import Store, now_iso

iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
NOW = datetime.now(timezone.utc)


def _json3(tmp_path, events):
    p = tmp_path / "subs.en.json3"
    p.write_text(json.dumps({"events": events}))
    return p


# ---------------------------------------------------------------- transcripts / moments
def test_json3_words_bleeps_and_brackets(tmp_path):
    p = _json3(tmp_path, [{"tStartMs": 1000, "segs": [{"utf8": "no"}, {"utf8": " way", "tOffsetMs": 300},
                                                       {"utf8": "[", "tOffsetMs": 500}, {"utf8": "__", "tOffsetMs": 600},
                                                       {"utf8": "]", "tOffsetMs": 700}]},
                          {"tStartMs": 3000, "segs": [{"utf8": "\n"}]}])
    w = moments.words_from_json3(p)
    assert [x["w"] for x in w] == ["no", "way", "****"]
    assert w[0]["t"] == 1.0 and w[1]["t"] == 1.3
    assert all(x["e"] > x["t"] for x in w)


def _words(n=600, hot_at=300):
    """1 word/s of filler, with an excited burst at hot_at."""
    out = []
    for i in range(n):
        txt = "and then we drive"
        if hot_at <= i < hot_at + 20:
            txt = "no way bro the cops chase crash"
        for j, tok in enumerate(txt.split()):
            t = i + j * 0.2
            out.append({"t": t, "e": t + 0.18, "w": tok})
    return out


def test_candidate_windows_find_hot_spot_and_dont_overlap():
    wins = moments.candidate_windows(_words(), [], 600, 30, top=4)
    assert 280 <= wins[0]["start"] <= 320
    spans = sorted((w["start"], w["end"]) for w in wins)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))


def test_heatmap_dominates_when_present():
    heat = [[s, s + 10, 1.0 if 500 <= s < 530 else 0.05] for s in range(0, 600, 10)]
    wins = moments.candidate_windows(_words(hot_at=100), heat, 600, 30, top=1)
    assert 470 <= wins[0]["start"] <= 530


# ---------------------------------------------------------------- scout scoring / rights
def test_score_rewards_velocity_relevance_rights_and_blocks_unsafe():
    from clipfarm.scout import score_candidate
    base = {"platform": "twitch", "views": 5000, "age_hours": 2, "relevant": True, "rights": "unverified"}
    s1 = score_candidate(dict(base))
    assert score_candidate(dict(base, rights="campaign")) > s1
    assert score_candidate(dict(base, relevant=False)) < s1
    assert score_candidate(dict(base, views=50000)) > s1
    assert score_candidate(dict(base, unsafe=True)) < 0


def test_rights_resolution_from_sources():
    lvl, _ = rights.resolve("twitch", "XQC")
    assert lvl == "unverified"
    assert rights.resolve("youtube", None, "Rockstar Games")[0] == "official"
    assert rights.resolve("twitch", "somebody-new")[0] == "unverified"
    assert not rights.auto_render_allowed("unverified") and rights.auto_render_allowed("campaign")


def test_select_candidates_gates_rights_and_creator_cap():
    for i, (ch, lvl) in enumerate([("a", "campaign"), ("a", "campaign"), ("a", "campaign"), ("b", "unverified")]):
        Store.upsert(Store.candidates, {"id": f"tw:{i}", "platform": "twitch", "channel": ch, "rights": lvl,
                                        "relevant": True, "score": 90 - i, "status": "new", "published_at": now_iso()})
    picked = pipeline.select_candidates(10)
    assert [c["id"] for c in picked] == ["tw:0", "tw:1"]  # cap 2/creator/day, unverified gated
    assert Store.get(Store.candidates, "tw:3")["status"] == "needs_rights"


# ---------------------------------------------------------------- planner
def test_pick_slots_spreads_evenly():
    slots = ["07:30", "11:30", "14:30", "17:30", "20:00", "22:30"]
    assert planner.pick_slots(slots, 3) == ["07:30", "14:30", "22:30"]
    assert planner.pick_slots(slots, 6) == slots and planner.pick_slots(slots, 0) == []


def test_plan_counts_and_production_need():
    Store.upsert(Store.clips, {"id": "c0001", "status": "approved", "score": 80})
    Store.upsert(Store.clips, {"id": "c0002", "status": "rendered"})
    p = planner.plan()
    assert p["phase"] in ("launch_surge", "growth", "steady") and p["target"] >= 2
    assert p["ready"] == 1 and p["in_review"] == 1
    assert p["renders_needed"] >= 0
    assert len(p["slots"]) == p["target"]


def test_performance_recommends_more_when_recent_beats_prior():
    for i in range(12):
        recent = i < 5
        Store.upsert(Store.clips, {"id": f"c{i + 1:04d}", "status": "posted",
                                   "posted_at": iso(NOW - timedelta(hours=30 if recent else 24 * 6)),
                                   "metrics": {"views": 9000 if recent else 2000}})
    perf = planner.performance({}, timezone.utc)
    assert perf["delta"] == 1


# ---------------------------------------------------------------- analytics
def test_tiktok_id_and_csv_parse():
    assert analytics.tiktok_id_from_url("https://www.tiktok.com/@x/video/7301234567890123456?lang=en") == "7301234567890123456"
    rows = analytics.parse_csv("Video link,Video views,Likes,Comments,Shares,Video title\n"
                               "https://www.tiktok.com/@x/video/7301234567890123456,12.5K,1200,3,5,hi\n")
    assert rows[0]["views"] == 12500 and rows[0]["likes"] == 1200


def test_record_updates_clip_metrics_autolinks_and_earnings():
    Store.upsert(Store.clips, {"id": "c0001", "status": "posted", "tiktok_id": "111", "campaign_id": "cr-gta6-tokyo-girl"})
    Store.upsert(Store.clips, {"id": "c0002", "status": "approved", "hook": "Gator ate the getaway car",
                               "caption": "Gator ate the getaway car — via xqc"})
    res = analytics.record([
        {"tiktok_id": "111", "views": 20000, "likes": 10, "comments": 1, "shares": 0},
        {"tiktok_id": "222", "views": 500, "description": "Gator ate the getaway car — via xqc #gta6", "created": NOW.timestamp()},
    ], {"followers": 50}, "test")
    assert res["auto_linked"] == 1
    c1, c2 = Store.get(Store.clips, "c0001"), Store.get(Store.clips, "c0002")
    assert c1["metrics"]["views"] == 20000 and c1["est_earnings"] == round(20 * 0.70 * 0.9, 2)
    assert c2["status"] == "posted" and c2["tiktok_id"] == "222" and c2["metrics"]["views"] == 500


# ---------------------------------------------------------------- brain (fake client, real response shape)
class _FakeMessages:
    def __init__(self, payload, stop="end_turn"):
        self.payload, self.stop, self.kwargs = payload, stop, None

    def create(self, **kw):
        self.kwargs = kw
        return SimpleNamespace(stop_reason=self.stop, content=[SimpleNamespace(type="thinking"),
                                                                SimpleNamespace(type="text", text=json.dumps(self.payload))])


def _fake_brain(monkeypatch, payload, stop="end_turn"):
    fm = _FakeMessages(payload, stop)
    monkeypatch.setattr(brain, "available", lambda: True)
    monkeypatch.setattr(brain, "_get_client", lambda: SimpleNamespace(beta=SimpleNamespace(messages=fm)))
    return fm


def test_brain_pick_moments_clamps_and_sends_structured_request(monkeypatch):
    fm = _fake_brain(monkeypatch, {"picks": [{"window": 0, "start": 0, "end": 999, "score": 88, "hook": "He did WHAT",
                                              "caption": "wild", "hashtags": ["gta6"], "reason": "chaos"},
                                             {"window": 7, "start": 1, "end": 2, "score": 1, "hook": "x", "caption": "x",
                                              "hashtags": [], "reason": "bad index"}]})
    picks = brain.pick_moments({"title": "t"}, [{"start": 100, "end": 130, "text": "no way"}], 2, (18, 45))
    assert len(picks) == 1
    assert picks[0]["start"] == 92 and picks[0]["end"] - picks[0]["start"] <= 45
    kw = fm.kwargs
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default"
    assert kw["output_config"]["format"]["type"] == "json_schema" and "thinking" not in kw


def test_brain_refusal_falls_back(monkeypatch):
    _fake_brain(monkeypatch, {"picks": []}, stop="refusal")
    assert brain.pick_moments({}, [{"start": 0, "end": 30, "text": ""}], 1, (18, 45)) is None


# ---------------------------------------------------------------- render + full produce (needs ffmpeg)
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def test_build_ass_escapes_and_highlights():
    ass = render.build_ass([{"t": 1.0, "e": 1.4, "w": "{evil}"}, {"t": 1.4, "e": 1.8, "w": "[laughter]"},
                            {"t": 1.8, "e": 2.2, "w": "go"}], 0, 10, "Hook {x}", "via xqc", "blurpad", {})
    assert "{evil}" not in ass and "(EVIL)" in ass and "[LAUGHTER]" not in ass
    assert "HOOK (X)" in ass and "via xqc" in ass and "\\c&H00E5FF&" in ass


@needs_ffmpeg
def test_produce_end_to_end_local_source(tmp_path, monkeypatch):
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=70",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=70", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", str(src)], check=True)
    _fake_brain(monkeypatch, {"picks": [{"window": 0, "start": 10, "end": 30, "score": 90, "hook": "Wait for it",
                                         "caption": "GTA 6 chaos — via me #gta6", "hashtags": ["gta6", "vicecity"],
                                         "reason": "test"}]})
    monkeypatch.setattr(moments, "whisper_words", lambda media: [{"t": 11.0, "e": 11.5, "w": "no"}, {"t": 11.5, "e": 12.0, "w": "way"}])
    res = pipeline._clip_url({"url": str(src), "rights": "own", "start": 10, "end": 30})
    assert len(res["clips"]) == 1
    clip = Store.get(Store.clips, res["clips"][0])
    assert clip["status"] == "rendered" and clip["qc"]["ok"], clip.get("qc")
    assert clip["qc"]["width"] == 1080 and clip["qc"]["height"] == 1920 and 19 <= clip["qc"]["duration"] <= 21
    assert "#gta6" in clip["caption"] and "#vicecity" in clip["caption"]
    assert server.clip_action(clip["id"], {"action": "approve"})["status"] == "approved"
    posted = server.clip_action(clip["id"], {"action": "posted", "tiktok_url": "https://www.tiktok.com/@a/video/7301234567890123456"})
    assert posted["tiktok_id"] == "7301234567890123456"


# ---------------------------------------------------------------- TikTok drafts hand-off
def test_drafts_view_and_drafted_status_flow(farm_root):
    clip_file = farm_root / "media" / "clips" / "c0001.mp4"
    clip_file.parent.mkdir(parents=True, exist_ok=True)
    clip_file.write_bytes(b"x" * 2048)
    Store.upsert(Store.clips, {"id": "c0001", "status": "approved", "score": 90, "hook": "Gator ate the car",
                               "caption": "Gator ate the car\n\n#gta6", "file": "media/clips/c0001.mp4"})
    Store.upsert(Store.clips, {"id": "c0002", "status": "approved", "score": 50, "hook": "h2", "caption": "c2",
                               "file": "media/clips/missing.mp4"})
    view = server.drafts_view()
    assert view["mode"] == "UPLOAD_TO_DRAFT" and view["is_aigc"] is False
    first = view["to_send"][0]
    assert first["id"] == "c0001" and first["file_exists"] and first["file"].endswith("c0001.mp4")
    assert first["title"] == "Gator ate the car" and "#gta6" in first["description"]
    assert view["to_send"][1]["file_exists"] is False

    out = server.clip_action("c0001", {"action": "drafted", "publish_id": "p123", "publish_session_id": "s1"})
    assert out["status"] == "drafted" and out["draft"]["publish_id"] == "p123" and out["draft"]["sent_at"]
    view = server.drafts_view()
    assert [c["id"] for c in view["to_send"]] == ["c0002"]
    assert view["in_tiktok_drafts"][0]["id"] == "c0001" and view["in_tiktok_drafts"][0]["publish_id"] == "p123"

    p = planner.plan()
    assert p["ready"] == 2 and p["in_drafts"] == 1
    assigned = [b for b in p["slots"] if b["state"] == "assigned"]
    if assigned:  # a drafted clip takes the next open slot ahead of merely-approved ones
        assert assigned[0]["clip_id"] == "c0001" and assigned[0]["in_drafts"]

    # once it is live, metrics auto-link it by caption and mark it posted
    analytics.record([{"tiktok_id": "999", "views": 10, "description": "Gator ate the car #gta6", "created": NOW.timestamp()}], {}, "test")
    assert Store.get(Store.clips, "c0001")["status"] == "posted"


def test_local_path_vs_url_source(tmp_path):
    with pytest.raises(RuntimeError, match="file not found"):
        render.fetch_source({"id": "url:x", "url": str(tmp_path / "nope.mp4")}, 0, 5)


# ---------------------------------------------------------------- TikTok API: one-click drafts
import hashlib  # noqa: E402
import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, HTTPServer  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402

from clipfarm import core, tiktok  # noqa: E402


class FakeTikTok:
    """A local stand-in for TikTok's API, so the real HTTP code (headers, ranges, bytes) runs."""

    def __init__(self):
        self.received = b""
        self.ranges, self.inits, self.token_calls = [], [], []
        self.init_error = None
        self.open_id = "u1"
        self.bearer, self.bearer_of = [], {}
        self.status = "SEND_TO_USER_INBOX"
        self.post_ids = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                raw = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if self.path.endswith("/oauth/token/"):
                    f = {k: v[0] for k, v in parse_qs(body.decode()).items()}
                    fake.token_calls.append(f)
                    at = f"at{len(fake.token_calls)}"
                    fake.bearer_of[fake.open_id] = "Bearer " + at
                    return self._send(200, {"access_token": at, "expires_in": 7200,
                                            "refresh_token": f"rt{len(fake.token_calls)}", "refresh_expires_in": 15552000,
                                            "open_id": fake.open_id, "scope": "user.info.basic,video.upload", "token_type": "Bearer"})
                assert self.headers["Authorization"].startswith("Bearer at")
                fake.bearer.append(self.headers["Authorization"])
                if self.path.endswith("/inbox/video/init/"):
                    if fake.init_error:
                        return self._send(403, {"data": {}, "error": {"code": fake.init_error, "message": "x", "log_id": "l"}})
                    fake.inits.append(json.loads(body))
                    return self._send(200, {"data": {"publish_id": "v_inbox_file~v2.1",
                                                     "upload_url": f"http://127.0.0.1:{fake.port}/upload?upload_id=1"},
                                            "error": {"code": "ok", "message": "", "log_id": "l"}})
                if self.path.endswith("/status/fetch/"):
                    return self._send(200, {"data": {"status": fake.status, "publicaly_available_post_id": fake.post_ids},
                                            "error": {"code": "ok", "message": "", "log_id": "l"}})
                return self._send(404, {})

            def do_GET(self):  # noqa: N802
                if "/user/info/" in self.path:
                    return self._send(200, {"data": {"user": {"open_id": fake.open_id, "display_name": f"Name of {fake.open_id}"}},
                                            "error": {"code": "ok", "message": "", "log_id": "l"}})
                return self._send(404, {})

            def do_PUT(self):  # noqa: N802
                n = int(self.headers["Content-Length"])
                data = self.rfile.read(n)
                rng = self.headers["Content-Range"]
                first, rest = rng.removeprefix("bytes ").split("-")
                last, total = rest.split("/")
                assert int(first) == len(fake.received) and int(last) - int(first) + 1 == n
                assert self.headers["Content-Type"] == "video/mp4"
                fake.received += data
                fake.ranges.append(rng)
                self.send_response(201 if len(fake.received) == int(total) else 206)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def fake_tiktok(monkeypatch, farm_root):
    fake = FakeTikTok()
    monkeypatch.setattr(tiktok, "API", f"http://127.0.0.1:{fake.port}/v2/")
    monkeypatch.setattr(tiktok.time, "sleep", lambda s: None)
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "ck")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "cs")
    from clipfarm import accounts
    accounts.TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)

    def wipe():
        accounts.TOKENS_FILE.unlink(missing_ok=True)
        cfg = core.load_config()
        cfg.pop("accounts", None)
        core.save_config(cfg)
    wipe()
    yield fake
    fake.httpd.shutdown()
    wipe()


def _approved_clip(farm_root, cid="c0001", size=3000):
    f = farm_root / "media" / "clips" / f"{cid}.mp4"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(bytes(range(256)) * (size // 256) + b"z" * (size % 256))
    Store.upsert(Store.clips, {"id": cid, "status": "approved", "score": 80, "hook": "h", "caption": "c",
                               "file": f"media/clips/{cid}.mp4"})
    return f


def test_tiktok_login_uses_desktop_pkce_and_saves_rotating_tokens(fake_tiktok):
    url = tiktok.authorize_url(8787)
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert q["client_key"] == "ck" and q["response_type"] == "code" and q["code_challenge_method"] == "S256"
    assert q["redirect_uri"] == "http://127.0.0.1:8787/auth/tiktok/callback/"
    assert q["scope"] == "user.info.basic,video.upload"
    with pytest.raises(tiktok.TikTokError):
        tiktok.finish_login("code", "wrong-state", 8787)
    url = tiktok.authorize_url(8787)
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    tiktok.finish_login("the-code", q["state"], 8787)
    sent = fake_tiktok.token_calls[-1]
    assert sent["grant_type"] == "authorization_code" and sent["code"] == "the-code"
    assert 43 <= len(sent["code_verifier"]) <= 128
    assert hashlib.sha256(sent["code_verifier"].encode()).hexdigest() == q["code_challenge"]  # hex, per TikTok
    assert tiktok.status_summary(8787)["can_upload"] is True
    # expired access token -> refresh, and the rotated refresh token is the one kept
    from clipfarm import accounts
    acct = accounts.all_accounts("tiktok")[0]
    assert acct["platform"] == "tiktok" and acct["mode"] == "drafts" and acct["handle"] == "chat.clip.that"
    tok = accounts.token(acct["id"])
    tok["obtained_at"] -= 7200
    accounts.set_token(acct["id"], tok)
    assert tiktok.access_token(acct["id"]) == "at2"
    assert fake_tiktok.token_calls[-1]["refresh_token"] == "rt1"
    assert accounts.token(acct["id"])["refresh_token"] == "rt2" and accounts.token(acct["id"])["open_id"] == "u1"


def test_chunk_plan_follows_tiktok_rules():
    assert tiktok.chunk_plan(3_000_000) == (3_000_000, 1)            # under 5 MB: whole file
    assert tiktok.chunk_plan(64_000_000) == (64_000_000, 1)
    size = 150_000_001
    chunk, count = tiktok.chunk_plan(size)
    assert chunk == 10_000_000 and count == 15
    assert size - (count - 1) * chunk <= 128_000_000                 # final chunk absorbs the remainder


def test_send_clip_uploads_and_marks_drafted_then_posted(fake_tiktok, farm_root):
    f = _approved_clip(farm_root)
    tiktok.finish_login("c", parse_qs(urlparse(tiktok.authorize_url(8787)).query)["state"][0], 8787)
    out = server.clip_action("c0001", {"action": "send_to_drafts"})
    assert out["sending"] is True
    for _ in range(100):  # the dashboard runs the upload as a background job
        if Store.get(Store.clips, "c0001")["status"] == "drafted":
            break
        threading.Event().wait(0.05)
    clip = Store.get(Store.clips, "c0001")
    assert clip["status"] == "drafted" and clip["sending"] is False
    assert clip["draft"]["via"] == "tiktok_api" and clip["draft"]["publish_id"] == "v_inbox_file~v2.1"
    assert clip["draft"]["state"] == "SEND_TO_USER_INBOX"
    assert fake_tiktok.received == f.read_bytes() and fake_tiktok.ranges == ["bytes 0-2999/3000"]
    assert fake_tiktok.inits[0] == {"source_info": {"source": "FILE_UPLOAD", "video_size": 3000,
                                                    "chunk_size": 3000, "total_chunk_count": 1}}
    assert tiktok.pending_count() == 1
    # the user posts it from TikTok -> the next sync marks it posted with the video id
    fake_tiktok.status, fake_tiktok.post_ids = "PUBLISH_COMPLETE", [7301234567890123456]
    assert tiktok.sync_drafts() == {"posted": 1, "failed": 0}
    clip = Store.get(Store.clips, "c0001")
    assert clip["status"] == "posted" and clip["tiktok_id"] == "7301234567890123456"
    assert clip["tiktok_url"].endswith("/video/7301234567890123456")


def test_send_clip_chunked_upload_sends_exact_bytes(fake_tiktok, farm_root, monkeypatch):
    f = _approved_clip(farm_root, size=1050)
    monkeypatch.setattr(tiktok, "SINGLE_PUT_MAX", 1000)
    monkeypatch.setattr(tiktok, "CHUNK", 400)
    tiktok.finish_login("c", parse_qs(urlparse(tiktok.authorize_url(8787)).query)["state"][0], 8787)
    tiktok.send_clip("c0001")
    assert fake_tiktok.ranges == ["bytes 0-399/1050", "bytes 400-1049/1050"]
    assert fake_tiktok.received == f.read_bytes()
    assert fake_tiktok.inits[0]["source_info"]["total_chunk_count"] == 2


def test_send_clip_failure_keeps_clip_approved_with_plain_error(fake_tiktok, farm_root):
    _approved_clip(farm_root)
    tiktok.finish_login("c", parse_qs(urlparse(tiktok.authorize_url(8787)).query)["state"][0], 8787)
    fake_tiktok.init_error = "spam_risk_too_many_pending_share"
    with pytest.raises(tiktok.TikTokError, match="5 unposted drafts"):
        tiktok.send_clip("c0001")
    clip = Store.get(Store.clips, "c0001")
    assert clip["status"] == "approved" and clip["sending"] is False and "5 unposted drafts" in clip["draft_error"]
    assert fake_tiktok.received == b""


def test_send_requires_connection_and_approval(fake_tiktok, farm_root):
    _approved_clip(farm_root)
    with pytest.raises(ValueError, match="connect TikTok"):
        server.clip_action("c0001", {"action": "send_to_drafts"})
    Store.update(Store.clips, "c0001", status="rendered")
    with pytest.raises(ValueError, match="approve"):
        server.clip_action("c0001", {"action": "send_to_drafts"})


def test_dashboard_keys_are_stored_locally_and_never_echoed(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    core.KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    core.save_keys({"ANTHROPIC_API_KEY": "  sk-ant-test-1234567890  "})
    try:
        import os
        assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-test-1234567890"
        view = server.connections_view()
        assert view["keys"]["ANTHROPIC_API_KEY"] == {"set": True, "source": "dashboard", "hint": "…7890"}
        assert "sk-ant-test" not in json.dumps(view)
        with pytest.raises(ValueError):
            core.save_keys({"PATH": "/evil"})
    finally:
        core.save_keys({"ANTHROPIC_API_KEY": ""})
    assert server.connections_view()["keys"]["ANTHROPIC_API_KEY"]["set"] is False


def test_tiktok_web_login_via_https_forwarding_page(fake_tiktok, monkeypatch):
    page = "https://example.github.io/repo/tiktok-callback/"
    cfg = core.load_config()
    cfg.setdefault("tiktok", {})["redirect_uri"] = page
    monkeypatch.setattr(tiktok, "load_config", lambda: cfg)
    q = {k: v[0] for k, v in parse_qs(urlparse(tiktok.authorize_url(8787)).query).items()}
    assert q["redirect_uri"] == page and "code_challenge" not in q      # web flow: no PKCE
    tiktok.finish_login("the-code", q["state"], 8787)
    sent = fake_tiktok.token_calls[-1]
    assert sent["redirect_uri"] == page and "code_verifier" not in sent
    assert tiktok.status_summary(8787)["default_redirect_uri"] == "http://127.0.0.1:8787/auth/tiktok/callback/"


# ---------------------------------------------------------------- no-commentary gameplay + full auto
def test_energy_windows_find_the_loud_action_and_start_just_before_it():
    rms = [-50.0] * 600
    for i in range(300, 318):
        rms[i] = -12.0 if i % 3 else -30.0     # bursts of gunfire
    wins = moments.energy_windows(rms, 600, 30, top=3)
    assert wins and wins[0]["no_speech"] and 290 <= wins[0]["start"] <= 300
    assert wins[0]["end"] - wins[0]["start"] == 30 and "no speech" in wins[0]["text"]
    assert moments.energy_windows([-50.0] * 20, 20, 30, top=3) == []      # too short to rank


@needs_ffmpeg
def test_silent_gameplay_link_still_makes_a_clip_and_full_auto_approves_it(tmp_path, monkeypatch):
    """The user's real failure: a video with no commentary produced nothing."""
    src = tmp_path / "gameplay.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=150",
                    "-f", "lavfi", "-i", "sine=frequency=200:duration=150", "-f", "lavfi", "-i", "anoisesrc=d=150:a=0.9",
                    "-filter_complex", "[1:a]volume=0.02[q];[2:a]volume='if(between(t,90,104),1,0)':eval=frame[b];[q][b]amix=inputs=2:normalize=0[o]",
                    "-map", "0:v", "-map", "[o]", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(src)], check=True)
    monkeypatch.setattr(brain, "pick_moments", lambda *a, **k: None)          # no key: heuristics pick
    monkeypatch.setattr(moments, "whisper_words", lambda media: [])
    seen = {}

    def fake_review(grid, hook, title, niche=None):
        seen["grid_exists"] = grid.is_file()
        return {"approve": True, "quality": 82, "nsfw": False, "reason": "Clear action."}
    monkeypatch.setattr(brain, "review_clip", fake_review)
    cfg = core.load_config()
    cfg["produce"]["auto_approve"] = {"enabled": True}
    cfg["produce"]["include_unverified"] = True
    monkeypatch.setattr(pipeline, "load_config", lambda: cfg)
    monkeypatch.setattr(rights, "load_config", lambda: cfg)
    res = pipeline._clip_url({"url": str(src)})                               # rights default: unverified
    assert len(res["clips"]) >= 1
    clip = Store.get(Store.clips, res["clips"][0])
    assert 80 <= clip["start"] <= 92, clip["start"]                           # lands on the loud section
    assert clip["status"] == "approved" and clip["auto_decided"] and clip["review"]["quality"] == 82
    assert clip["rights"] == "unverified" and seen["grid_exists"]
    assert clip["qc"]["ok"] and clip["qc"]["height"] == 1920


def test_auto_approve_respects_the_rights_switch_and_rejects_nsfw(monkeypatch):
    cfg = core.load_config()
    cfg["produce"]["auto_approve"] = {"enabled": True}
    monkeypatch.setattr(pipeline, "load_config", lambda: cfg)
    monkeypatch.setattr(rights, "load_config", lambda: cfg)
    monkeypatch.setattr(moments, "fetch_youtube_words", lambda c: [])
    monkeypatch.setattr(moments, "find_moments", lambda c, w: [{"start": 0, "end": 20, "score": 90, "hook": "h",
                                                                 "caption": "c", "hashtags": [], "source": "brain"}])
    monkeypatch.setattr(render, "render_clip", lambda *a: {"file": "f.mp4", "thumb": None, "grid": "g.jpg",
                                                            "qc": {"ok": True, "issues": []}, "layout": "blurpad"})
    verdict = {"approve": True, "quality": 90, "nsfw": False, "reason": "ok"}
    monkeypatch.setattr(brain, "review_clip", lambda *a: dict(verdict))
    base = {"platform": "youtube", "url": "https://youtu.be/x", "channel": "c", "duration": 100, "title": "t"}

    def make(cid, level):
        Store.upsert(Store.candidates, {**base, "id": cid, "rights": level, "status": "queued"})
        return Store.get(Store.clips, pipeline.produce_candidate(Store.get(Store.candidates, cid))[0])
    assert make("yt:a", "unverified")["status"] == "rendered"      # switch off: a person decides
    assert make("yt:b", "permission")["status"] == "approved"
    cfg["produce"]["include_unverified"] = True
    assert make("yt:c", "unverified")["status"] == "approved"      # the user turned "any creator" on
    verdict.update(approve=False, quality=20, reason="menu screen")
    rejected = make("yt:d", "permission")
    assert rejected["status"] == "rejected" and rejected["reject_reason"] == "menu screen"
    cfg["produce"]["auto_approve"] = {"enabled": False}
    verdict.update(approve=True, quality=95, nsfw=True)
    assert make("yt:e", "permission")["status"] == "rejected"      # sexual content never queues


def test_any_creator_switch_releases_sources_that_were_waiting(monkeypatch):
    Store.upsert(Store.candidates, {"id": "yt:1", "platform": "youtube", "rights": "unverified", "relevant": True,
                                    "score": 90, "status": "needs_rights", "published_at": now_iso()})
    assert pipeline.select_candidates(3) == []
    cfg = core.load_config()
    cfg["produce"]["include_unverified"] = True
    monkeypatch.setattr(rights, "load_config", lambda: cfg)
    assert [c["id"] for c in pipeline.select_candidates(3)] == ["yt:1"]


def test_auto_send_tick_only_runs_when_switched_on_and_connected(monkeypatch, fake_tiktok, farm_root):
    _approved_clip(farm_root)
    started = []
    monkeypatch.setattr(pipeline, "start_job", lambda kind, params=None: started.append((kind, params)))
    cfg = core.load_config()
    monkeypatch.setattr(pipeline, "load_config", lambda: cfg)
    pipeline._last_auto_send[0] = 0.0
    pipeline.auto_send_tick()
    assert started == []                                           # switch off
    cfg.setdefault("tiktok", {})["auto_send"] = True
    pipeline.auto_send_tick()
    assert started == []                                           # not connected
    tiktok.finish_login("c", parse_qs(urlparse(tiktok.authorize_url(8787)).query)["state"][0], 8787)
    pipeline.auto_send_tick()
    assert started and started[0][0] == "send_drafts" and 1 <= started[0][1]["max"] <= 5
    pipeline.auto_send_tick()
    assert len(started) == 1                                       # waits 10 minutes before trying again


# ---------------------------------------------------------------- over real HTTP, as the browser calls it
def _post(port, path, body):
    import urllib.request
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(), method="POST",
                                 headers={"X-Clipfarm": "1", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def test_scout_buttons_work_over_http_with_encoded_ids():
    from http.server import ThreadingHTTPServer
    from urllib.parse import quote
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        for cid in ("yt:JEaW9KnTijQ", "yt:other-vid_2"):
            Store.upsert(Store.candidates, {"id": cid, "platform": "youtube", "channel": "Some Creator",
                                            "channel_id": "UC123", "rights": "unverified", "status": "needs_rights"})
        enc = quote("yt:JEaW9KnTijQ", safe="")              # what encodeURIComponent sends: yt%3AJEaW9KnTijQ
        assert "%3A" in enc
        out = _post(port, f"/api/candidates/{enc}", {"rights": "permission", "apply_channel": True})   # Trust channel
        assert out["rights"] == "permission"
        assert rights.resolve("youtube", "UC123")[0] == "permission"
        sibling = Store.get(Store.candidates, "yt:other-vid_2")
        assert sibling["rights"] == "permission" and sibling["status"] == "new"
        assert _post(port, f"/api/candidates/{enc}", {"action": "skip"})["status"] == "skipped"       # Skip
        assert _post(port, f"/api/candidates/{enc}", {"action": "queue"})["status"] == "queued"       # Clip
    finally:
        httpd.shutdown()
        src = core.load_sources()                            # leave the shared test config as it was
        src["channels"] = [c for c in src["channels"] if c.get("id") != "UC123"]
        core.save_sources(src)


# ---------------------------------------------------------------- visual picking + source ranking
def test_pick_moments_sends_frames_and_stays_text_only_without_them(monkeypatch, tmp_path):
    sheet = tmp_path / "w0.jpg"
    sheet.write_bytes(b"\xff\xd8fakejpeg")
    pick = {"window": 1, "start": 200, "end": 228, "score": 80, "hook": "h", "caption": "c", "hashtags": [], "reason": "r"}
    fm = _fake_brain(monkeypatch, {"picks": [pick]})
    wins = [{"start": 100, "end": 130, "text": "calm"}, {"start": 200, "end": 230, "text": "chase"}]
    out = brain.pick_moments({"title": "t"}, wins, 2, (18, 45), [sheet, None])
    assert out[0]["start"] == 200
    content = fm.kwargs["messages"][0]["content"]
    kinds = [b["type"] for b in content]
    assert kinds == ["text", "text", "image", "text"]                 # image follows only the window that has one
    assert content[2]["source"]["media_type"] == "image/jpeg" and "SEE" in content[0]["text"]
    brain.pick_moments({"title": "t"}, wins, 2, (18, 45), [None, None])
    assert isinstance(fm.kwargs["messages"][0]["content"], str)       # no frames: plain text request


@needs_ffmpeg
def test_window_previews_make_one_sheet_per_window(tmp_path):
    src = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=40",
                    "-c:v", "libx264", "-preset", "ultrafast", str(src)], check=True)
    sheets = moments.window_previews({"id": "url:pv", "url": str(src)}, [{"start": 2, "end": 20}, {"start": 20, "end": 38}])
    assert all(s and s.is_file() for s in sheets) and sheets[0] != sheets[1]
    assert render.probe(sheets[0])["width"] == 768                    # 2x2 frames of 384 px


def test_scout_prefers_highlights_over_marathons_and_slow_walkthroughs():
    from clipfarm.scout import score_candidate
    base = {"platform": "youtube", "views": 500000, "age_hours": 10, "relevant": True, "rights": "unverified", "duration": 900}
    plain = score_candidate(dict(base, title="GTA 6 gameplay"))
    assert score_candidate(dict(base, title="GTA 6 funny moments and police chase")) > plain
    assert score_candidate(dict(base, title="GTA 6 Gameplay Walkthrough Part 1 FULL GAME")) < plain
    assert score_candidate(dict(base, title="GTA 6 gameplay", duration=24 * 3600)) < plain - 30


# ---------------------------------------------------------------- phone page
def test_phone_page_gate_and_content(monkeypatch):
    cfg = core.load_config()
    monkeypatch.setattr("clipfarm.phone.load_config", lambda: cfg)
    from clipfarm import phone
    key = phone.token()
    assert phone.is_local("127.0.0.1") and not phone.is_local("192.168.1.20")
    assert not phone.lan_allowed("/phone", key)                        # switched off by default
    cfg["phone"] = {"enabled": True}
    assert phone.lan_allowed("/phone", key) and phone.lan_allowed("/media/clips/c0001.mp4", key)
    assert not phone.lan_allowed("/phone", "wrong") and not phone.lan_allowed("/phone", None)
    for path in ("/", "/api/state", "/api/connections", "/static/app.js", "/media/work/x.mp4", "/media/clips/../x.mp4", "/auth/tiktok"):
        assert not phone.lan_allowed(path, key), path
    Store.upsert(Store.clips, {"id": "c0001", "status": "drafted", "hook": "<b>Gator</b> ate it", "duration": 30,
                               "caption": "He did <script>x</script>\n\n#gta6", "thumb": "media/clips/c0001.jpg", "file": "media/clips/c0001.mp4"})
    Store.upsert(Store.clips, {"id": "c0002", "status": "rendered", "hook": "not approved", "caption": "hidden"})
    page = phone.render_page(key)
    assert "&lt;b&gt;Gator&lt;/b&gt; ate it" in page and "<script>x</script>" not in page
    assert "#gta6" in page and "in your TikTok drafts" in page and "not approved" not in page
    assert f"/media/clips/c0001.mp4?k={key}" in page


def test_other_devices_reach_only_the_phone_page_over_http(monkeypatch):
    from http.server import ThreadingHTTPServer
    import urllib.error
    import urllib.request
    from clipfarm import phone
    ip = phone.lan_ip()
    if not ip:
        pytest.skip("no network interface besides loopback")
    cfg = core.load_config()
    cfg["phone"] = {"enabled": True}
    monkeypatch.setattr("clipfarm.phone.load_config", lambda: cfg)
    httpd = ThreadingHTTPServer(("0.0.0.0", 0), server.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def code(url, **kw):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, **kw), timeout=10) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
    try:
        lan, key = f"http://{ip}:{port}", phone.token()
        assert code(f"{lan}/phone?k={key}") == 200
        assert code(f"{lan}/phone?k=nope") == 403 and code(f"{lan}/phone") == 403
        assert code(f"{lan}/") == 403 and code(f"{lan}/api/state?k={key}") == 403 and code(f"{lan}/api/connections?k={key}") == 403
        assert code(f"{lan}/api/config?k={key}", data=b'{"phone":{"enabled":false}}', method="POST",
                    headers={"X-Clipfarm": "1"}) == 403                # the network can never change settings
        assert code(f"http://127.0.0.1:{port}/api/state") == 200       # this computer still has everything
        cfg["phone"] = {"enabled": False}
        assert code(f"{lan}/phone?k={key}") == 403
    finally:
        httpd.shutdown()


# ---------------------------------------------------------------- niches
@pytest.fixture
def clean_config():
    """Snapshot config/account.json (in the throwaway test root) and restore it afterwards."""
    before = json.dumps(core.load_config())
    yield
    core.save_config(json.loads(before))


def test_default_niche_is_gta_and_new_niches_get_their_own_searches_and_tags(clean_config):
    from clipfarm import niches
    first = niches.all_niches()
    assert [n["id"] for n in first] == ["gta6"] and "GTA 6 police chase" in first[0]["queries"]
    assert niches.is_relevant(first[0], "Lucia robs a bank in Vice City") and not niches.is_relevant(first[0], "Minecraft speedrun")
    with pytest.raises(ValueError, match="at least one search"):
        niches.upsert({"name": "Empty"})
    pod = niches.upsert({"name": "Podcast clips", "brief": "Funny and heated podcast moments.", "queries": "podcast funny moments\njoe rogan clip",
                         "relevance": "podcast, rogan, interview", "hashtags": "podcast, #Clips"})
    assert pod["id"] == "podcast-clips" and pod["queries"] == ["podcast funny moments", "joe rogan clip"]
    assert pod["hashtags"] == ["#podcast", "#clips"]
    assert [n["id"] for n in niches.all_niches()] == ["gta6", "podcast-clips"]     # the default was kept
    assert niches.match("Joe Rogan interview gets heated")["id"] == "podcast-clips"
    assert niches.match("GTA 6 police chase")["id"] == "gta6" and niches.match("cooking pasta") is None
    assert not niches.is_relevant(pod, "broadcasting live")                         # whole words only
    # captions and Claude's brief follow the clip's niche
    cap, tags = pipeline._compose_caption({"caption": "He lost it", "hashtags": ["funny"]}, {"niche": "podcast-clips"}, core.load_config())
    assert tags[:3] == ["#funny", "#podcast", "#clips"] and "#gta6" not in cap
    assert "Podcast clips" in brain.editor_system(pod) and "always include #podcast" in brain.editor_system(pod)
    assert "GTA 6" in brain.editor_system(None) and "Podcast clips" in brain.reviewer_system(pod)
    niches.remove("podcast-clips")
    with pytest.raises(ValueError, match="at least one"):
        niches.remove("gta6")


def test_scout_searches_each_niche_and_tags_what_it_finds(monkeypatch, clean_config):
    from clipfarm import niches, scout
    niches.upsert({"name": "Podcast clips", "queries": ["podcast funny moments"], "relevance": "podcast"})
    searched = []

    def fake_run_json(cmd, timeout=180):
        url = cmd[-1]
        searched.append(url)
        vid = "podvid00001" if "podcast" in url else "gtavid00001"
        title = "Podcast gets heated" if "podcast" in url else "GTA 6 police chase goes wrong"
        return {"entries": [{"id": vid, "title": title, "view_count": 5000, "duration": 600}]}
    monkeypatch.setattr(scout, "run_json", fake_run_json)
    monkeypatch.setattr(scout, "youtube_meta", lambda url: {"channel": "Chan", "channel_id": "UCx", "published_at": now_iso(), "duration": 600})
    monkeypatch.setattr(scout, "scout_twitch", lambda cfg: [])
    scout.run_scout({"podcast-clips": ["podcast trend query"]})
    cands = {c["id"]: c for c in Store.all(Store.candidates)}
    assert cands["yt:gtavid00001"]["niche"] == "gta6" and cands["yt:gtavid00001"]["relevant"]
    assert cands["yt:podvid00001"]["niche"] == "podcast-clips" and cands["yt:podvid00001"]["relevant"]
    assert any("podcast+trend+query" in u for u in searched)


# ---------------------------------------------------------------- several accounts
def _login(fake, open_id):
    fake.open_id = open_id
    return tiktok.finish_login("c", parse_qs(urlparse(tiktok.authorize_url(8787)).query)["state"][0], 8787)


def test_two_accounts_split_clips_by_niche_and_each_gets_its_own_drafts(fake_tiktok, farm_root, clean_config):
    from clipfarm import accounts
    a = _login(fake_tiktok, "user-a")
    b = _login(fake_tiktok, "user-b")
    assert a["id"] != b["id"] and len(accounts.all_accounts("tiktok")) == 2
    assert _login(fake_tiktok, "user-a")["id"] == a["id"] and len(accounts.all_accounts("tiktok")) == 2   # re-login, no duplicate
    accounts.update(a["id"], {"niches": ["gta6"], "posts_per_day": 3, "handle": "@gta.page"})
    accounts.update(b["id"], {"niches": ["podcast-clips"], "posts_per_day": 20})
    assert accounts.get(a["id"])["handle"] == "gta.page" and accounts.get(b["id"])["posts_per_day"] == 15   # capped
    for i, niche in enumerate(["gta6", "gta6", "podcast-clips", "cooking"]):
        _approved_clip(farm_root, cid=f"c000{i + 1}")
        Store.update(Store.clips, f"c000{i + 1}", niche=niche)
    p = planner.plan()
    by = {x["id"]: x for x in p["accounts"]}
    assert by[a["id"]]["target"] == 3 and by[b["id"]]["target"] == 15 and p["target"] == 18
    assert by[a["id"]]["ready"] == 2 and by[b["id"]]["ready"] == 1 and p["unplaced"] == 1    # nobody takes "cooking"
    owner = {c["id"]: c.get("account_id") for c in Store.all(Store.clips)}
    assert owner["c0001"] == owner["c0002"] == a["id"] and owner["c0003"] == b["id"] and not owner["c0004"]
    assert all(s.get("account") for s in p["slots"]) and len(by[b["id"]]["slots"]) == 15

    out = tiktok.send_clip("c0003")
    assert out["account"] == b["id"]
    assert tiktok.pending_count(b["id"]) == 1 and tiktok.pending_count(a["id"]) == 0
    assert fake_tiktok.bearer[-1] != fake_tiktok.bearer_of["user-a"]                         # sent with B's login
    st = tiktok.status_summary(8787)
    assert len(st["accounts"]) == 2 and st["can_upload"] and st["pending_cap"] == 10

    tiktok.disconnect(b["id"])
    assert [x["id"] for x in accounts.all_accounts("tiktok")] == [a["id"]] and accounts.token(b["id"]) is None


def test_old_single_login_becomes_the_first_account(farm_root, clean_config):
    from clipfarm import accounts
    accounts.TOKENS_FILE.unlink(missing_ok=True)
    accounts.LEGACY_TIKTOK_TOKEN.parent.mkdir(parents=True, exist_ok=True)
    core.write_json(accounts.LEGACY_TIKTOK_TOKEN, {"access_token": "at", "refresh_token": "rt", "open_id": "legacy-user",
                                                   "scope": "user.info.basic,video.upload", "obtained_at": 9e9, "expires_in": 7200})
    Store.upsert(Store.clips, {"id": "c0001", "status": "drafted", "draft": {"via": "tiktok_api", "publish_id": "p1", "sent_at": now_iso()}})
    try:
        accts = accounts.all_accounts("tiktok")
        assert len(accts) == 1 and accts[0]["handle"] == "chat.clip.that" and accts[0]["mode"] == "drafts"
        assert not accounts.LEGACY_TIKTOK_TOKEN.exists() and accounts.token(accts[0]["id"])["open_id"] == "legacy-user"
        assert Store.get(Store.clips, "c0001")["account_id"] == accts[0]["id"]
        assert tiktok.pending_count(accts[0]["id"]) == 1 and tiktok.status_summary(8787)["can_upload"]
    finally:
        accounts.TOKENS_FILE.unlink(missing_ok=True)


def test_more_posts_than_named_slots_are_spread_through_the_day():
    slots = ["07:30", "11:30", "14:30", "17:30", "20:00", "22:30"]
    out = planner.pick_slots(slots, 15)
    assert len(out) == 15 and out[0] == "07:30" and out[-1] == "22:30" and out == sorted(out) and len(set(out)) == 15

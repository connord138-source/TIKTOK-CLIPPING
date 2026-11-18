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
                    return self._send(200, {"access_token": f"at{len(fake.token_calls)}", "expires_in": 7200,
                                            "refresh_token": f"rt{len(fake.token_calls)}", "refresh_expires_in": 15552000,
                                            "open_id": "u1", "scope": "user.info.basic,video.upload", "token_type": "Bearer"})
                assert self.headers["Authorization"].startswith("Bearer at")
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
    tiktok.TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tiktok.TOKEN_FILE.unlink(missing_ok=True)
    yield fake
    fake.httpd.shutdown()
    tiktok.TOKEN_FILE.unlink(missing_ok=True)


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
    tok = tiktok.token()
    tok["obtained_at"] -= 7200
    core.write_json(tiktok.TOKEN_FILE, tok)
    assert tiktok.access_token() == "at2"
    assert fake_tiktok.token_calls[-1]["refresh_token"] == "rt1" and tiktok.token()["refresh_token"] == "rt2"


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

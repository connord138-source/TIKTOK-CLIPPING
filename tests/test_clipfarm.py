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

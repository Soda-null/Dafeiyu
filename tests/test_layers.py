"""The three layers of her character (decision 13): A base that drifts a notch a month inside
bounds, B a phase with inertia, C the hour-scale mood that wakes up where B puts it."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from fish.brain import Brain, FakeLLM
from fish.config import Settings
from fish.memory import Diary, MemoryStore, PhaseStore, Relationship, TraitStore
from fish.memory.traits import MAX_STEP, TRAITS
from fish.mood import Mood, MoodStore
from fish.routines import run_nightly
from fish.storage import connect

T = datetime(2026, 10, 26, 20, 0)


def test_phase_moves_a_fifth_of_the_way_each_night(tmp_path):
    ps = PhaseStore(connect(tmp_path / "f.db"))
    p0 = ps.current()
    assert (p0.tone, p0.drive, p0.line) == (0.1, 0.6, "")
    p1 = ps.update("2026-10-26", tone_today=1.0, drive_today=0.2, focus=["候鸟"], line="迷上候鸟")
    assert p1.tone == pytest.approx(0.8 * 0.1 + 0.2 * 1.0) and p1.drive == pytest.approx(0.8 * 0.6 + 0.2 * 0.2)
    p2 = ps.update("2026-10-27", tone_today=None, drive_today=None)  # a day without data
    assert (p2.tone, p2.drive, p2.line, p2.focus) == (p1.tone, p1.drive, "迷上候鸟", ("候鸟",))
    for i in range(10):  # ten good days in a row: tone climbs, never past 1
        ps.update(f"2026-11-{i + 1:02d}", tone_today=1.0, drive_today=1.0)
    assert 0.85 < ps.current().tone <= 1.0 and ps.current().tone_word == "偏好"


def test_traits_start_at_the_origin_and_cannot_jump(tmp_path):
    ts = TraitStore(connect(tmp_path / "f.db"))
    assert ts.values()["guard"] == TRAITS["guard"][0] and ts.describe() == []
    applied = ts.apply({"guard": 0.5, "talk": -0.02, "nonsense": 1.0, "tease": "x"}, T)
    assert applied == {"guard": MAX_STEP, "talk": -0.02}
    assert ts.values()["guard"] == pytest.approx(TRAITS["guard"][0] + MAX_STEP)
    for _ in range(40):
        ts.apply({"guard": 0.15}, T)
    assert ts.values()["guard"] == 1.0  # the bound holds
    assert ts.describe() == ["比刚认识时敞开了些"]


def test_mood_wakes_up_where_the_phase_puts_her(tmp_path):
    store = MoodStore(connect(tmp_path / "f.db"))
    assert store.rest(tone=-1.0, drive=0.0).energy == 30 and store.load().boredom == 30
    assert store.rest(tone=1.0, drive=1.0).energy == 90 and store.load().boredom == 10


def make(tmp_path: Path, llm):
    conn = connect(tmp_path / "fish.db")
    s = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db")
    return conn, Brain(conn, s, llm, persona_text="你是大肥鱼。")


def layered_llm(growth_changes=None):
    def respond(messages, json_mode):
        content = messages[-1]["content"]
        if "你在写日记" in content:
            return json.dumps({"diary": "数米粒。", "self_notes": [], "phase_line": "这周有点蔫"}, ensure_ascii=False)
        if "回头看看这一个月的自己" in content:
            assert "guard（防备↔敞开）" in content
            return json.dumps({"note": "这个月话多了点，可能是他老来。",
                               "changes": growth_changes or {"talk": 0.3, "guard": 0.1}}, ensure_ascii=False)
        if "这次和他的聊天结束了" in content:
            return json.dumps({"summary": "s", "gist": "g", "importance": 4, "valence": 0, "notes": [], "followups": []})
        return json.dumps({"say": "嗯", "mood": "开心", "topic": "闲聊"})
    return FakeLLM(respond)


def test_a_day_of_happy_turns_lifts_the_phase_and_the_night_resets_the_mood(tmp_path):
    conn, brain = make(tmp_path, layered_llm())
    for i in range(6):
        brain.respond(f"第{i}句", now=T + timedelta(minutes=i))
    mood = MoodStore(conn).load()
    assert mood.energy < 70  # six turns cost a little
    report = run_nightly(conn, datetime(2026, 10, 27, 3, 30), brain=brain)
    phase = PhaseStore(conn).current()
    assert phase.line == "这周有点蔫" and phase.tone > 0.1  # 开心 all day nudged the tone up
    assert report["phase"] == {"tone": round(phase.tone, 2), "drive": round(phase.drive, 2)}
    assert MoodStore(conn).load().energy == pytest.approx(30 + 60 * phase.drive)
    assert "growth" not in report  # not a month in yet


def test_monthly_growth_moves_the_base_a_notch_and_shows_in_the_prompt(tmp_path):
    conn, brain = make(tmp_path, layered_llm())
    rel = Relationship(conn)
    rel.set("first_met", "2026-09-20")
    brain.window.append("user", "你好", "wechat", None, datetime(2026, 10, 25, 12, 0))
    for d in range(1, 8):
        Diary(conn).write(f"2026-10-{d:02d}", f"第{d}天的日记")
    report = run_nightly(conn, datetime(2026, 10, 27, 3, 30), brain=brain)
    assert report["growth"] == {"talk": MAX_STEP, "guard": 0.1}  # 0.3 was clipped to a notch
    ts = TraitStore(conn)
    (note,) = ts.growth_notes()
    assert note.text.startswith("这个月话多了点") and note.month == "2026-10-26"
    assert [m.text for m in MemoryStore(conn).alive("self")][-1].endswith("这个月话多了点，可能是他老来。")
    # a second night does not review again
    assert "growth" not in run_nightly(conn, datetime(2026, 10, 28, 3, 30), brain=brain)
    # once the slider has moved enough, the chat prompt says so
    ts.apply({"talk": 0.15}, T)
    brain.respond("在吗", now=datetime(2026, 10, 28, 12, 0))
    system = brain.llm.calls[-1][0][0]["content"]
    assert "比刚认识时话多了些" in system and "这个月话多了点" in system

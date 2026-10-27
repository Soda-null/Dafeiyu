"""The night's model steps with a scripted model: diary, merges, replacements, reflection, export."""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from fish.brain import Brain, FakeLLM
from fish.config import Settings
from fish.memory import Diary, EpisodeManager, MemoryStore
from fish.routines import diary_day, fish_day, run_nightly
from fish.storage import connect

NIGHT = datetime(2026, 10, 27, 3, 30)  # closes the fish day 2026-10-26
PERSONA = "你是大肥鱼。"


def scripted(diary="数了 300 粒米，他今天挺慌的。", merges=None, updates=None, insights=None):
    def respond(messages, json_mode):
        content = messages[-1]["content"]
        if "你在写日记" in content:
            return json.dumps({"diary": diary, "self_notes": [{"text": "米粒数到 300 了", "importance": 4}]},
                              ensure_ascii=False)
        if "看起来很像" in content:
            return json.dumps({"merges": merges or []}, ensure_ascii=False)
        if "说法不同" in content:
            return json.dumps({"updates": updates or []}, ensure_ascii=False)
        if "想看出点规律" in content:
            return json.dumps({"insights": insights or []}, ensure_ascii=False)
        if "这次和他的聊天结束了" in content:
            return json.dumps({"summary": "聊了演示", "gist": "他很慌", "importance": 5, "valence": -0.3,
                               "notes": [], "followups": []}, ensure_ascii=False)
        return json.dumps({"say": "嗯"}, ensure_ascii=False)
    return FakeLLM(respond)


def make(tmp_path: Path, llm):
    conn = connect(tmp_path / "fish.db")
    settings = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db")
    return conn, Brain(conn, settings, llm, persona_text=PERSONA)


def prompt_of(llm: FakeLLM, marker: str) -> str:
    return next(m[-1]["content"] for m, _ in llm.calls if marker in m[-1]["content"])


def test_day_boundary_is_half_past_three():
    assert fish_day(datetime(2026, 10, 27, 1, 0)) == date(2026, 10, 26)
    assert fish_day(datetime(2026, 10, 27, 3, 30)) == date(2026, 10, 27)
    assert diary_day(NIGHT) == date(2026, 10, 26)
    assert diary_day(datetime(2026, 10, 27, 10, 0)) == date(2026, 10, 26)
    assert diary_day(datetime(2026, 10, 27, 2, 0)) == date(2026, 10, 25)


def test_diary_is_written_from_the_days_chats_and_keeps_her_threads(tmp_path):
    llm = scripted()
    conn, brain = make(tmp_path, llm)
    store = MemoryStore(conn)
    store.add("self", "开始数鱼缸里的米粒", importance=4, now=NIGHT - timedelta(days=1))
    em = EpisodeManager(conn)
    ep = em.start("wechat", datetime(2026, 10, 26, 20, 0))
    brain.window.append("user", "周五演示好慌", "wechat", ep.id, datetime(2026, 10, 26, 20, 1))
    em.close(ep.id, summary="聊了演示", gist="他为周五的演示发愁", importance=6, valence=-0.3,
             now=datetime(2026, 10, 26, 20, 30))
    Diary(conn).write("2026-10-25", "他没来。")

    report = run_nightly(conn, NIGHT, brain=brain, export_path=tmp_path / "notebook.md")
    assert report["day"] == "2026-10-26" and report["diary"] is True
    prompt = prompt_of(llm, "你在写日记")
    assert "他为周五的演示发愁" in prompt and "开始数鱼缸里的米粒" in prompt and "他没来。" in prompt
    assert Diary(conn).recent(1) == [("2026-10-26", "数了 300 粒米，他今天挺慌的。")]
    assert [m.text for m in store.alive("self")] == ["开始数鱼缸里的米粒", "米粒数到 300 了"]
    assert "数了 300 粒米" in (tmp_path / "notebook.md").read_text(encoding="utf-8")
    assert run_nightly(conn, NIGHT + timedelta(hours=6), brain=brain) == {"skipped": True}


def test_duplicates_are_merged_and_replacements_supersede(tmp_path):
    conn, brain = make(tmp_path, scripted())
    store = MemoryStore(conn)
    old_a = store.add("fact", "他不吃香菜", importance=5, tags=["香菜"], now=NIGHT - timedelta(days=3))
    new_a = store.add("fact", "他说不吃香菜，味道像肥皂", importance=5, tags=["香菜"],
                      now=datetime(2026, 10, 26, 21, 0))
    old_b = store.add("fact", "他的演示在周五", importance=6, tags=["演示"], now=NIGHT - timedelta(days=2))
    new_b = store.add("fact", "演示改到周四了", importance=6, tags=["演示"], now=datetime(2026, 10, 26, 22, 0))
    brain.llm = scripted(merges=[{"ids": [new_a.id, old_a.id], "text": "他不吃香菜，说味道像肥皂"}],
                         updates=[{"old_id": old_b.id, "new_id": new_b.id}])

    report = run_nightly(conn, NIGHT, brain=brain)
    assert report["merged"] == 1 and report["updated"] == 1
    alive = {m.text for m in store.alive("fact")}
    assert alive == {"他不吃香菜，说味道像肥皂", "演示改到周四了"}
    assert store.get(old_b.id).superseded_by == new_b.id
    merged = next(m for m in store.alive("fact") if m.merged_from)
    assert set(merged.merged_from) == {old_a.id, new_a.id}


def test_reflection_runs_after_five_chats_and_adds_insights(tmp_path):
    llm = scripted(insights=[{"text": "他最近总是半夜才来找我", "importance": 7},
                             {"text": "太低", "importance": 2}])
    conn, brain = make(tmp_path, llm)
    em = EpisodeManager(conn)
    for i in range(5):
        start = datetime(2026, 10, 22 + (i % 4), 20, i)
        ep = em.start("wechat", start)
        em.close(ep.id, summary=f"第{i}次", gist=f"第{i}次聊天", importance=4, valence=0,
                 now=start + timedelta(minutes=10))

    report = run_nightly(conn, NIGHT, brain=brain)
    assert report["insights"] == 2
    insights = MemoryStore(conn).alive("insight")
    assert [m.text for m in insights] == ["他最近总是半夜才来找我", "太低"]
    assert [m.importance for m in insights] == [7, 6]  # clamped to 6..8
    assert "第4次聊天" in prompt_of(llm, "想看出点规律")
    # the next night: only one new chat, less than a week -> no reflection
    ep = em.start("wechat", datetime(2026, 10, 27, 20, 0))
    em.close(ep.id, summary="x", gist="x", importance=3, valence=0, now=datetime(2026, 10, 27, 20, 5))
    assert "insights" not in run_nightly(conn, NIGHT + timedelta(days=1), brain=brain)


def test_a_bad_model_reply_leaves_the_night_to_the_mechanical_steps(tmp_path):
    conn, brain = make(tmp_path, FakeLLM(lambda m, j: "这不是 json"))
    em = EpisodeManager(conn)
    ep = em.start("wechat", datetime(2026, 10, 26, 20, 0))
    em.close(ep.id, summary="s", gist="g", importance=3, valence=0, now=datetime(2026, 10, 26, 20, 5))
    report = run_nightly(conn, NIGHT, brain=brain)
    assert report["skipped"] is False and "diary" not in report
    assert Diary(conn).recent(1) == []


def test_without_a_brain_only_mechanical_steps_run(tmp_path):
    conn, _ = make(tmp_path, scripted())
    report = run_nightly(conn, NIGHT)
    assert set(report) == {"skipped", "day", "compressed", "expired", "phase"}


def test_no_diary_for_days_before_the_first_chat(tmp_path):
    conn, brain = make(tmp_path, scripted())
    brain.window.append("user", "你好", "terminal", now=datetime(2026, 10, 28, 12, 0))
    assert "diary" not in run_nightly(conn, NIGHT, brain=brain)  # closes 10-26: before they met
    assert run_nightly(conn, datetime(2026, 10, 29, 3, 30), brain=brain)["diary"] is True

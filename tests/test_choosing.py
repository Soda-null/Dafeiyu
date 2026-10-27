"""Choosing before writing (decision 19): notes about the chat itself are not kept, repeats
reinforce the old memory, insights and howto rules are capped, her life grows by at most one
thread a night."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from fish.brain import Brain, FakeLLM
from fish.config import Settings
from fish.memory import MemoryStore
from fish.memory.longterm import KIND_CAPS, overlap
from fish.routines import run_nightly
from fish.storage import connect

T0 = datetime(2026, 10, 26, 20, 0)


@pytest.fixture
def store(tmp_path):
    return MemoryStore(connect(tmp_path / "fish.db"))


def test_notes_about_the_chat_itself_are_not_kept(store):
    assert store.note("insight", "他考我记性的次数越来越密", importance=7, now=T0) is None
    assert store.note("event", "他问我记不记得他学什么专业", importance=4, now=T0) is None
    assert store.note("fact", "他学机械，大二", importance=8, now=T0) is not None
    assert store.note("self", "我记性越来越差，米粒数乱了", importance=3, now=T0) is not None  # her own life
    assert [m.text for m in store.alive()] == ["他学机械，大二", "我记性越来越差，米粒数乱了"]


def test_her_life_threads_are_not_about_him(store):
    assert store.note("self", "他最近失眠，还没解决。", importance=3, now=T0) is None
    assert store.note("self", "他每晚数米粒，数到四十八", importance=3, now=T0) is None  # the pronoun went wrong
    assert store.note("self", "我老是打算盯着他别碰花生", importance=3, now=T0) is not None


def test_a_repeat_reinforces_the_old_memory(store):
    old = store.note("self", "想给鱼缸加点芦苇和水草，弄成湿地那样，说不定有鸟来", importance=3, now=T0)
    again = store.note("self", "鱼缸想加水草，弄成湿地那样，盼着有鸟来", importance=4, now=T0 + timedelta(days=5))
    assert again.id == old.id and again.recall_count == 1 and again.stability > old.stability
    assert len(store.alive("self")) == 1
    other = store.note("self", "想换个有大窗、能看见树影的鱼缸", importance=4, now=T0 + timedelta(days=5))
    assert other.id != old.id  # same topic, different thought: kept


def test_facts_need_to_be_nearly_the_same_to_count_as_a_repeat(store):
    store.note("fact", "他住3号楼", importance=6, now=T0)
    moved = store.note("fact", "他住7号楼", importance=6, now=T0 + timedelta(days=14))
    assert len(store.alive("fact")) == 2 and moved.text == "他住7号楼"  # a correction, for the nightly check
    store.note("fact", "他住7号楼", importance=6, now=T0 + timedelta(days=15))
    assert len(store.alive("fact")) == 2


def test_the_same_thing_every_week_is_one_memory_that_happened_often(store):
    """Decision 20: a repeat across days counts one more time instead of a new memory."""
    store.note("event", "2026-10-26 他下午有实验课，没法翘课", importance=4, now=T0)
    store.note("event", "2026-11-02 他下午有实验课，没法翘课", importance=4, now=T0 + timedelta(days=7))
    m = store.note("event", "2026-11-09 他下午有实验课，翘不了", importance=4, now=T0 + timedelta(days=14))
    assert len(store.alive("event")) == 1 and m.times == 3 and m.often == "好几回了"
    assert m.line().endswith("（好几回了）")
    assert overlap("2026-10-26 他下午有实验课", "2026年10月27日 他下午有实验课") == 1.0  # dates do not count


def test_counting_to_three_asks_for_a_gist_and_the_night_writes_it(tmp_path):
    """She keeps that she counted rice many times, not what number she reached each night."""
    def respond(messages, json_mode):
        text = messages[-1]["content"]
        if "夜里整理小本本" in text and "（3 回）" in text:
            assert "（3 回）" in text
            return json.dumps({"gists": [{"id": 1, "text": "我老在睡前数米粒，数过好多回，总数不到头"}]},
                              ensure_ascii=False)
        return "{}"

    conn = connect(tmp_path / "fish.db")
    store = MemoryStore(conn)
    for i, n in enumerate(("三十七", "四十一", "四十四")):
        store.note("self", f"睡前数米粒，今天数到{n}就乱了", importance=3, now=T0 + timedelta(days=i))
    (m,) = store.alive("self")
    assert m.times == 3 and m.gist_due and store.gists_due() == [m]
    settings = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db")
    brain = Brain(conn, settings, FakeLLM(respond), persona_text="你是大肥鱼。")
    report = run_nightly(conn, T0 + timedelta(days=2, hours=8), brain=brain)
    (m,) = store.alive("self")
    assert report["gists"] == 1 and m.text == "我老在睡前数米粒，数过好多回，总数不到头"
    assert m.times == 3 and not m.gist_due and m.line().endswith("（好几回了）")
    for _ in range(3):  # 6 times: due again
        store.note("self", "睡前数米粒，今天数到五十就乱了", importance=3, now=T0 + timedelta(days=5))
    assert store.get(m.id).gist_due and store.get(m.id).often == "很多回了"


def test_a_fact_said_again_is_confirmed_not_happening_often(store):
    """His birthday said three times is still one birthday: counted, never "好几回", no gist."""
    for i in range(3):
        m = store.note("fact", "他的生日是3月14日", importance=8, now=T0 + timedelta(days=i))
    assert m.times == 3 and not m.gist_due and m.often == "" and m.line() == "他的生日是3月14日"
    for i in range(3):
        h = store.note("howto", "他饿着赶路时直接催他先吃", importance=6, now=T0 + timedelta(days=i))
    assert h.times == 3 and not h.gist_due and h.line() == h.text


def test_her_prompt_says_how_often(tmp_path):
    from fish.brain.prompt import render_recalled
    from fish.memory.retrieval import recall

    store = MemoryStore(connect(tmp_path / "fish.db"))
    for day in range(6):
        store.note("event", "他周五吃食堂的糖醋排骨", importance=4, now=T0 + timedelta(days=7 * day))
    got = recall(store, "糖醋排骨", T0 + timedelta(days=36))
    assert "他周五吃食堂的糖醋排骨（很多回了）" in render_recalled(got)


INSIGHTS = ["他早上不爱说话", "下雨天他心情差", "考完试他就想吃火锅", "他一忙就不回消息", "他喜欢被损两句",
            "周末他睡到中午", "他提到妹妹就开心", "他对导师有点怕", "熬夜后他脾气大", "他嘴硬心软",
            "他打球回来特别话多", "饿了他会变得暴躁", "他爱拿外号逗人", "他做项目很较真", "他不喜欢被催",
            "他说笑死就是真开心", "他一紧张就刷视频", "他对钱算得很细", "他听歌循环同一首", "他晚饭吃得随便",
            "他一考完试就想吃火锅和烧烤"]


def test_insights_are_capped_and_the_weakest_goes(store):
    cap = KIND_CAPS["insight"]
    assert max(overlap(a, b) for i, a in enumerate(INSIGHTS[:cap]) for b in INSIGHTS[i + 1:cap]) < 0.5
    first = [store.note("insight", INSIGHTS[i], importance=6 if i else 7, now=T0 + timedelta(minutes=i))
             for i in range(cap)]
    assert len(store.alive("insight")) == cap
    newest = store.note("insight", "他背包里总带着一把伞", importance=6, now=T0 + timedelta(days=1))
    alive = store.alive("insight")
    assert len(alive) == cap and newest in alive
    assert first[0].id in {m.id for m in alive}  # importance 7 is the most stable: it stays
    assert store.get(first[1].id).superseded_by == newest.id  # the least stable, oldest of its kind


def test_her_life_grows_by_one_thread_a_night(tmp_path):
    def respond(messages, json_mode):
        text = messages[-1]["content"]
        if "写日记" in text:
            return json.dumps({"diary": "数米粒。", "phase_line": "",
                               "self_notes": [{"text": "开始数米粒", "importance": 3},
                                              {"text": "想给鱼缸换个大窗", "importance": 5},
                                              {"text": "学会了吐泡泡", "importance": 4}]}, ensure_ascii=False)
        return "{}"

    conn = connect(tmp_path / "fish.db")
    settings = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db")
    brain = Brain(conn, settings, FakeLLM(respond), persona_text="你是大肥鱼。")
    brain.window.append("user", "你好", "wechat", None, T0)
    run_nightly(conn, T0 + timedelta(hours=8), brain=brain)
    assert [m.text for m in MemoryStore(conn).alive("self")] == ["想给鱼缸换个大窗"]


def test_chat_notes_go_through_the_choice(tmp_path):
    reply = {"say": "记住了", "mood": "平静", "topic": "专业", "followups": [], "asked": [], "corrections": [],
             "notes": [{"text": "他学机械，大二", "kind": "fact", "importance": 8},
                       {"text": "他在考我记不记得他的专业", "kind": "event", "importance": 4}]}
    conn = connect(tmp_path / "fish.db")
    settings = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db")
    brain = Brain(conn, settings, FakeLLM(lambda m, j: json.dumps(reply, ensure_ascii=False)),
                  persona_text="你是大肥鱼。")
    brain.respond("我学机械的，大二", now=T0)
    brain.respond("你记得我学啥的不", now=T0 + timedelta(minutes=5))
    facts = MemoryStore(conn).alive()
    assert [m.text for m in facts] == ["他学机械，大二"] and facts[0].recall_count >= 1

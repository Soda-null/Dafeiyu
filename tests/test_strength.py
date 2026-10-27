"""Memory v2 step 2 (decision 21): strength comes from how moved she was and what a memory
is about; lifelong things are pinned; insights and howto rules start unconfirmed and need
three days of evidence; rules she sees are outdated fade."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from fish.brain import Brain, FakeLLM
from fish.brain.parse import parse_notes
from fish.config import Settings
from fish.memory import MemoryStore
from fish.memory import stability as st
from fish.routines import run_nightly
from fish.storage import connect

T0 = datetime(2026, 10, 26, 20, 0)


@pytest.fixture
def store(tmp_path):
    return MemoryStore(connect(tmp_path / "fish.db"))


def test_strength_comes_from_what_it_is_about_and_how_moved(store):
    meal = store.note("event", "他中午吃了面", importance=5, about="路过", arousal=0.1, now=T0)
    school = store.note("fact", "他学机械，大二", importance=5, about="本人", arousal=0.3, now=T0)
    assert meal.stability == pytest.approx(4 * 1.3 * 1)  # fades in about two weeks
    assert school.stability == pytest.approx(4 * 1.9 * 40)  # most of a year before it blurs
    assert school.about == "本人" and school.importance == st.importance_of(school.stability)
    assert school in store.profile()  # facts about him himself are always in mind


def test_lifelong_things_are_pinned(store):
    birthday = store.note("fact", "他生日 3 月 14 日", importance=5, about="一辈子", arousal=0.6, now=T0)
    assert birthday.pinned and birthday.importance == 10
    assert birthday.retrievability(T0 + timedelta(days=3650)) == 1.0


def test_without_the_new_fields_the_old_rule_still_works(store):
    m = store.note("event", "他去打球了", importance=4, now=T0)
    assert m.about is None and m.stability == pytest.approx(st.initial_stability(4))


def test_a_new_rule_is_unconfirmed_and_fades_in_two_weeks(store):
    rule = store.note("insight", "他老是半夜才来找我", importance=8, now=T0)  # the model sounds sure
    assert rule.unconfirmed and rule.stability == st.UNCONFIRMED_DAYS
    assert rule.line() == "他老是半夜才来找我（还说不准）"
    assert rule.retrievability(T0 + timedelta(days=17)) < st.FREE_RECALL_R  # R = e^(-17/7) ≈ 0.09


def test_three_days_of_evidence_confirm_a_rule_and_one_day_does_not(store):
    rule = store.note("howto", "他饿着赶路时直接催他先吃", importance=6, now=T0)
    for h in (1, 2, 3):  # said again the same evening: still one day of evidence
        store.note("howto", "他饿着赶路时直接催他先吃", importance=6, now=T0 + timedelta(hours=h / 10))
    assert store.get(rule.id).unconfirmed and store.get(rule.id).times == 1
    store.note("howto", "他饿着赶路时直接催他先吃", importance=6, now=T0 + timedelta(days=2))
    rule = store.note("howto", "他饿着赶路时直接催他先吃", importance=6, now=T0 + timedelta(days=5))
    assert not rule.unconfirmed and rule.about == "本人" and rule.times == 3
    assert rule.stability >= st.stability_from("本人", 0.0) and rule.line() == rule.text


def test_notes_in_a_reply_carry_about_and_arousal():
    (n, m) = parse_notes([{"text": "他生日3月14", "kind": "fact", "about": "一辈子", "arousal": 0.7},
                          {"text": "他吃了面", "kind": "event", "about": "随便", "arousal": "高"}])
    assert (n.about, n.arousal) == ("一辈子", 0.7) and (m.about, m.arousal) == (None, 0.0)


def test_reflection_can_see_a_rule_is_outdated_and_it_fades(tmp_path):
    def respond(messages, json_mode):
        text = messages[-1]["content"]
        if "想看出点规律" in text:
            assert "[#1] 他老是半夜才来找我（还说不准）" in text
            return json.dumps({"insights": [{"text": "他现在白天来找我", "importance": 7}], "outdated": [1, 99]},
                              ensure_ascii=False)
        return "{}"

    conn = connect(tmp_path / "fish.db")
    settings = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db")
    brain = Brain(conn, settings, FakeLLM(respond), persona_text="你是大肥鱼。")
    store = MemoryStore(conn)
    old = store.note("insight", "他老是半夜才来找我", importance=7, now=T0 - timedelta(days=3))
    brain.window.append("user", "中午好", "wechat", None, T0)
    from fish.memory import EpisodeManager
    em = EpisodeManager(conn)
    for i in range(5):
        ep = em.start("wechat", T0 - timedelta(days=2, hours=i))
        em.close(ep.id, summary=f"第{i}次", gist=f"第{i}次聊天", importance=4, valence=0, now=T0)
    report = run_nightly(conn, T0 + timedelta(hours=8), brain=brain)
    assert report["outdated"] == 1  # 99 is not one of hers: ignored
    weak = store.get(old.id)
    assert weak.stability == st.WEAKENED_DAYS and weak.retrievability(T0 + timedelta(days=8)) < st.FREE_RECALL_R


def test_a_passing_state_does_not_go_on_his_card(store):
    sore = store.note("fact", "他上周喊得很凶，嗓子不舒服，还没好", importance=5, about="本人", arousal=0.3, now=T0)
    sister = store.note("fact", "他妹妹叫小雨，读高二", importance=5, about="本人", arousal=0.3, now=T0)
    assert sore.about == "日常" and sore not in store.profile()
    assert sister.about == "本人" and sister in store.profile()


def test_his_birthday_said_two_ways_is_one_pinned_memory(store):
    a = store.note("fact", "他的生日是3月14日，说好到那天提醒他", importance=5, about="一辈子", arousal=0.6, now=T0)
    b = store.note("fact", "他的生日是3月14号", importance=5, about="一辈子", arousal=0.6, now=T0 + timedelta(days=3))
    assert b.id == a.id and b.times == 2 and len([m for m in store.alive("fact") if m.pinned]) == 1
    store.note("fact", "他住3号楼", importance=5, about="本人", arousal=0.2, now=T0)
    store.note("fact", "他住7号楼", importance=5, about="本人", arousal=0.2, now=T0 + timedelta(days=14))
    assert len([m for m in store.alive("fact") if "号楼" in m.text]) == 2  # a move is not a repeat


def test_reflection_only_reads_chats_since_last_time(tmp_path):
    prompts = []

    def respond(messages, json_mode):
        text = messages[-1]["content"]
        if "想看出点规律" in text:
            prompts.append(text)
            return json.dumps({"insights": [{"text": "他压力大就聊吃的", "importance": 7}]}, ensure_ascii=False)
        return "{}"

    conn = connect(tmp_path / "fish.db")
    settings = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db")
    brain = Brain(conn, settings, FakeLLM(respond), persona_text="你是大肥鱼。")
    from fish.memory import EpisodeManager
    em = EpisodeManager(conn)

    def chats(day, label):
        for i in range(5):
            ep = em.start("wechat", day + timedelta(minutes=10 * i))
            em.close(ep.id, summary=label, gist=f"{label}{i}", importance=4, valence=0, now=day + timedelta(minutes=10 * i + 5))

    chats(T0, "第一批")
    run_nightly(conn, T0 + timedelta(hours=8), brain=brain)
    chats(T0 + timedelta(days=1), "第二批")
    run_nightly(conn, T0 + timedelta(days=1, hours=8), brain=brain)
    assert len(prompts) == 2 and "第一批" in prompts[0]
    assert "第二批" in prompts[1] and "第一批" not in prompts[1]  # old chats are not new evidence
    rule = MemoryStore(conn).alive("insight")[0]
    assert rule.times == 2 and rule.unconfirmed  # two reflections on two different sets of chats

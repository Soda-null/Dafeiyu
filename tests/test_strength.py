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

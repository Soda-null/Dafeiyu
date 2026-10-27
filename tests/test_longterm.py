"""A memory's lifecycle and recall, on a temporary database, with the clock dialled by hand."""

from datetime import datetime, timedelta

import pytest

from fish.memory import MemoryStore, recall
from fish.memory import stability as st
from fish.storage import connect

T0 = datetime(2026, 10, 26, 20, 0)


@pytest.fixture
def store(tmp_path):
    return MemoryStore(connect(tmp_path / "fish.db"))


def test_add_and_round_trip(store):
    m = store.add("fact", "他在大学学机器人", importance=9, tags=["大学", "机器人"], now=T0)
    assert m.stability == pytest.approx(st.initial_stability(9))
    assert m.tags == ("大学", "机器人") and m.alive and not m.pinned
    assert store.get(m.id) == m
    with pytest.raises(ValueError):
        store.add("rumour", "x", importance=5)


def test_small_detail_fades_but_a_strong_cue_still_wakes_it(store):
    m = store.add("event", "2026-10-26 他中午吃了麻辣烫", importance=2, tags=["麻辣烫"], now=T0)
    later = T0 + timedelta(days=12)
    assert m.retrievability(later) < st.FREE_RECALL_R

    # free recall: a related line with no tag hit does not bring it back
    assert recall(store, "今天中午吃什么好", later) == []
    # recognition: the tag in the cue wakes it, marked as such
    hits = recall(store, "上次那个麻辣烫怎么样", later)
    assert [h.memory.id for h in hits] == [m.id]
    assert hits[0].cued and hits[0].fuzzy
    # and being recalled made it stronger and fresh
    assert store.get(m.id).stability > m.stability
    assert store.get(m.id).recall_count == 1


def test_core_fact_is_still_in_the_profile_after_400_days(store):
    core = store.add("fact", "他叫小杨，大三，学机器人", importance=10, now=T0)
    minor = store.add("fact", "他那天穿了蓝色外套", importance=3, now=T0)
    later = T0 + timedelta(days=400)
    assert core.pinned and core.retrievability(later) == 1.0
    assert [m.id for m in store.profile()] == [core.id]
    assert minor.retrievability(later) < st.CUED_RECALL_R
    assert recall(store, "蓝色外套", later) == []


def test_correction_supersedes_and_keeps_the_old_as_former(store):
    old = store.add("fact", "他周五有机器人演示", importance=6, tags=["演示"], now=T0)
    new = store.correct(old.id, "他周四有机器人演示（他改口说是周四）", now=T0 + timedelta(days=1))
    assert store.get(old.id).superseded_by == new.id
    assert [m.id for m in store.alive()] == [new.id]
    hits = recall(store, "演示准备得怎么样", T0 + timedelta(days=2))
    assert hits[0].memory.id == new.id
    assert hits[0].former.id == old.id


def test_merge_is_more_stable_and_remembers_its_sources(store):
    a = store.add("fact", "他不吃香菜", importance=5, tags=["香菜"], now=T0)
    b = store.add("fact", "他说香菜味道像肥皂", importance=4, tags=["香菜"], now=T0)
    merged = store.merge([a.id, b.id], "他不吃香菜，说味道像肥皂", now=T0 + timedelta(days=1))
    assert merged.merged_from == (a.id, b.id)
    assert merged.importance == 5
    assert merged.stability == pytest.approx(st.after_merge(a.stability, b.stability))
    assert [m.id for m in store.alive()] == [merged.id]


def test_recall_respects_k_and_character_budget(store):
    for i in range(10):
        store.add("event", f"第{i}次聊到考试，他说很慌" + "。" * 30, importance=5, tags=["考试"], now=T0)
    hits = recall(store, "考试", T0 + timedelta(hours=1), k=6, budget_chars=100)
    assert 1 <= len(hits) <= 6
    assert sum(len(h.memory.text) for h in hits) <= 100 or len(hits) == 1

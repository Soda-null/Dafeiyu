"""Window, episodes, follow-ups, relationship, diary, mood and the nightly routine."""

from datetime import datetime, timedelta

import pytest

from fish.memory import (Diary, EpisodeManager, MemoryStore, ProspectiveStore, Relationship,
                         Window)
from fish.mood import MoodStore
from fish.routines import run_nightly
from fish.storage import connect

T0 = datetime(2026, 10, 26, 20, 0)


@pytest.fixture
def conn(tmp_path):
    return connect(tmp_path / "fish.db")


def test_window_folds_the_oldest_turns_once_it_overflows(conn):
    w = Window(conn, size=4, fold_batch=2)
    for i in range(5):
        w.append("user" if i % 2 == 0 else "fish", f"m{i}", "terminal", episode_id=1)
    assert [t.text for t in w.recent(1)] == ["m1", "m2", "m3", "m4"]
    fold = w.to_fold(1)
    assert [t.text for t in fold] == ["m0", "m1"]
    w.mark_folded([t.id for t in fold])
    assert [t.text for t in w.recent(1)] == ["m2", "m3", "m4"]
    assert w.to_fold(1) == []
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 5  # nothing deleted


def test_episode_boundaries_by_gap_and_by_day(conn):
    em = EpisodeManager(conn)
    assert em.open_episode() is None
    ep = em.start("terminal", T0)
    em.touch(ep.id, T0 + timedelta(minutes=10))
    assert em.stale(T0 + timedelta(minutes=20)) is None
    assert em.stale(T0 + timedelta(minutes=41)).id == ep.id
    em.touch(ep.id, T0 + timedelta(hours=3, minutes=50))  # 23:50
    assert em.stale(T0 + timedelta(hours=4, minutes=5)).id == ep.id  # next day, short gap
    closed = em.close(ep.id, summary="聊了演示", gist="他紧张", importance=6, valence=-0.2,
                      now=T0 + timedelta(hours=4))
    assert not closed.open and em.open_episode() is None and em.recent()[0].id == ep.id


def test_followups_come_due_and_expire(conn):
    ps = ProspectiveStore(conn)
    f = ps.add("问他机器人演示怎么样", "2026-10-31", now=T0)
    assert ps.due(datetime(2026, 10, 30)) == []
    assert [x.id for x in ps.due(datetime(2026, 10, 31, 9))] == [f.id]
    assert ps.expire(datetime(2026, 11, 1)) == []  # due + 1 day: still within grace
    expired = ps.expire(datetime(2026, 11, 2))
    assert [x.id for x in expired] == [f.id] and ps.get(f.id).status == "expired"
    g = ps.add("问他论文投了没", "2026-11-01", now=T0)
    ps.close(g.id)
    assert ps.get(g.id).status == "asked" and ps.open() == []


def test_she_keeps_only_a_few_things_in_mind(conn):
    """At most five open follow-ups, and none that repeats an open one (decision 17)."""
    ps = ProspectiveStore(conn)
    assert ps.add("问他机器人演示怎么样", "2026-10-31", now=T0)
    assert ps.add("问问他机器人演示怎么样了", "2026-11-01", now=T0) is None  # the same thing again
    for i, what in enumerate(["期中考试", "面试", "看牙", "去外地", "论文截止", "搬家"]):
        ps.add(f"问他{what}的结果", f"2026-11-0{i + 2}", now=T0)
    assert len(ps.open()) == 5
    assert "搬家" not in "".join(f.text for f in ps.open())


def test_relationship_counts_days_and_streak(conn):
    r = Relationship(conn)
    r.note_active_day(T0)
    r.note_active_day(T0 + timedelta(hours=2))  # same day, no double count
    r.note_active_day(T0 + timedelta(days=1))
    r.note_active_day(T0 + timedelta(days=3))  # skipped a day: streak resets
    assert r.stats(T0 + timedelta(days=3)) == {"days_known": 4, "days_talked": 3, "streak": 1}


def test_diary_round_trip(conn):
    d = Diary(conn)
    d.write("2026-10-25", "他没来，吃了三碗饭")
    d.write("2026-10-26", "数了一下午米粒")
    assert d.recent(1) == [("2026-10-26", "数了一下午米粒")]


def test_mood_defaults_save_and_clock(conn):
    store = MoodStore(conn)
    m = store.load()
    store.save(m)
    assert store.load() == m
    night = MoodStore.apply_clock(store.load(), datetime(2026, 10, 26, 2, 0))
    assert night.energy < m.energy and "困" in night.describe()
    assert store.load() == m  # the clock never changes what is stored
    for _ in range(20):
        MoodStore.after_turn(m, "嗯", "嗯")
    store.save(m)
    rested = store.rest(tone=0.0, drive=0.6)  # the phase sets where she wakes up
    assert rested.energy == pytest.approx(66) and rested.hunger > m.hunger - 10
    assert store.rest(tone=0.0, drive=1.0).energy == 90 and store.rest(tone=0.0, drive=0.0).energy == 30


def test_claim_run_is_taken_once_even_across_connections(tmp_path):
    from fish.routines.runs import claim_run, last_run

    a = connect(tmp_path / "fish.db")
    b = connect(tmp_path / "fish.db")
    assert claim_run(a, "browse", "2026-10-26") is True
    assert claim_run(b, "browse", "2026-10-26") is False
    assert last_run(b, "browse") == "2026-10-26"
    assert claim_run(b, "browse", "2026-10-27") is True


def test_nightly_runs_once_a_day_and_lets_missed_followups_go(conn):
    ps = ProspectiveStore(conn)
    ps.add("问他演示怎么样", "2026-10-31", now=T0)
    em = EpisodeManager(conn)
    ep = em.start("terminal", T0)
    em.close(ep.id, summary="s", gist="g", importance=3, valence=0, now=T0 + timedelta(hours=1))

    night = datetime(2026, 11, 5, 3, 30)
    first = run_nightly(conn, night)
    assert (first["skipped"], first["expired"], first["compressed"], first["day"]) == \
        (False, 1, 1, "2026-11-04")
    assert run_nightly(conn, night + timedelta(hours=5)) == {"skipped": True}
    assert MemoryStore(conn).alive() == []  # memory v3: no "我一直没问成他" event
    assert ps.open() == []
    assert em.get(ep.id).level == 1

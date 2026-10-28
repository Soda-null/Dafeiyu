"""Memory v3 step 9, scripts/migrate_v3.py: a v2 database (a tiny made-up one in a temp dir,
never data/) brought to v3. A dry run touches nothing; --apply backs up first, never deletes,
and only does what needs the user's eye for the ids given."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest

from fish.memory import MemoryStore
from fish.storage import db as schema

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2027, 3, 9, 12, 0)


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


mig = load("migrate_v3")
V2_COLUMNS = ("times", "gist_due", "pattern", "about", "last_time")


def digest(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def contents(path: Path) -> list[str]:
    """What a database holds, row for row (a backup is the same rows, not the same bytes)."""
    conn = sqlite3.connect(path)
    try:
        return list(conn.iterdump()) + [f"user_version {conn.execute('PRAGMA user_version').fetchone()[0]}"]
    finally:
        conn.close()


def memory(conn, i, kind, text, created, *, ep=None, about=None, s=30.0, merged=(), tags=(), by=None):
    conn.execute("INSERT INTO memories (id, kind, text, created, source_episode, importance, stability,"
                 " last_recalled, superseded_by, merged_from, tags, about, last_time)"
                 " VALUES (?, ?, ?, ?, ?, 5, ?, ?, ?, ?, ?, ?, ?)",
                 (i, kind, text, created, ep, s, created, by, json.dumps(list(merged)),
                  json.dumps(list(tags), ensure_ascii=False), about, created[:10]))


@pytest.fixture
def v2(tmp_path) -> Path:
    """What memory v2 left behind for a friend in Springfield: one chat closed at night, a
    correction in the next one, merges and caps with no `why`, her own threads the merge gave
    to him, a promise filed as 日常, a follow-up with nothing behind it."""
    path = tmp_path / "fish.db"
    conn = sqlite3.connect(path)
    conn.executescript(schema.SCHEMA)
    for table, column, decl in schema.ADDED_COLUMNS:
        if column in V2_COLUMNS:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    conn.execute("PRAGMA user_version = 7")
    conn.execute("INSERT INTO episodes VALUES (1, '2027-03-01T20:00:00', '2027-03-01T21:00:00',"
                 " '2027-03-02T03:30:00', 'terminal', '', '他说明天去动物园', '动物园', 5, 0, 0)")
    conn.execute("INSERT INTO episodes VALUES (2, '2027-03-04T20:00:00', '2027-03-04T20:30:00',"
                 " '2027-03-04T21:30:00', 'terminal', '', '他说搬到7号楼了', '搬家', 5, 0, 0)")
    conn.execute("INSERT INTO messages VALUES (1, '2027-03-01T20:10:00', 'user',"
                 " '明天去Springfield动物园玩', 'terminal', 1, 0)")
    memory(conn, 1, "event", "他要去动物园玩", "2027-03-01T20:10:00", ep=1, about="日常", tags=["动物园"])
    memory(conn, 2, "event", "他今晚吃了苹果派", "2027-03-02T03:30:00", ep=1, about="路过", s=10.0,
           tags=["苹果派"])
    memory(conn, 3, "fact", "他答应寒假带我去看海", "2027-03-02T03:30:00", ep=1, about="日常", tags=["看海"])
    memory(conn, 4, "self", "我每晚数米粒", "2027-03-02T03:30:00", about="日常", by=6)
    memory(conn, 5, "self", "我数米粒数到五十", "2027-03-03T03:30:00", about="路过", by=6)
    memory(conn, 6, "self", "他每晚数米粒，数到五十", "2027-03-04T03:30:00", merged=[4, 5])
    memory(conn, 7, "howto", "他累的时候少说两句", "2027-03-02T03:30:00", about="待印证", by=8)
    memory(conn, 8, "howto", "他困的时候别追问", "2027-03-03T03:30:00", about="待印证", s=60.0)
    memory(conn, 9, "fact", "他住3号楼", "2027-03-01T20:20:00", ep=1, about="本人", by=10, tags=["宿舍"])
    memory(conn, 10, "fact", "他住7号楼", "2027-03-04T20:25:00", ep=1, about="本人", tags=["宿舍"])
    memory(conn, 11, "event", "他一直没问成他：动物园好玩吗", "2027-03-04T03:30:00", s=90.0)
    memory(conn, 12, "self", "我明天重新数", "2027-03-02T03:30:00", about="日常")
    memory(conn, 13, "event", "他2027-03-06周五去面试", "2027-03-04T20:20:00", ep=2, about="日常")
    conn.execute("INSERT INTO prospective (id, text, due, created, source_memory, status)"
                 " VALUES (1, '问问他动物园好玩吗', '2027-03-03', '2027-03-02T03:30:00', NULL, 'open')")
    conn.commit()
    conn.close()
    return path


def step(steps, number: str):
    return next(s for s in steps if s.title.startswith(number))


def open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_a_dry_run_touches_nothing_and_lists_what_waits_for_the_user(v2):
    before = digest(v2)
    steps, saved = mig.run(v2, NOW)
    assert saved is None and digest(v2) == before
    assert not list(v2.parent.glob("*.bak-v2*"))
    conn = open_db(v2)
    assert "why" not in {r[1] for r in conn.execute("PRAGMA table_info(memories)")}
    assert "预演" in mig.report(steps, saved)
    # what was worked out on the copy
    assert any("merge: 2" in line for line in step(steps, "2.").lines)
    subjects = " ".join(step(steps, "4.").candidates)
    assert "#6 " in subjects and "#11 " in subjects and "#12 " not in subjects
    assert [c.split()[0] for c in step(steps, "6.").candidates] == ["#3"]
    assert {c.split()[1] for c in step(steps, "7.").candidates} == {"#8", "#11"}
    assert step(steps, "5a.").candidates and "2027-03-05周五" in step(steps, "5a.").candidates[0]


def test_apply_backs_up_first_and_fills_what_v3_reads(v2):
    before = contents(v2)
    steps, saved = mig.run(v2, NOW, apply=True)
    assert saved == v2.with_name("fish.db.bak-v2") and contents(saved) == before
    conn = open_db(v2)
    row = {r["id"]: r for r in conn.execute("SELECT * FROM memories")}
    assert len(row) == 13 and conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
    assert (row[4]["why"], row[5]["why"], row[7]["why"], row[9]["why"]) == ("merge", "merge", "cap", "update")
    assert row[6]["about"] == "日常"  # the strongest of its sources
    # a chat note: the day his line names; a close note: dated at the chat, not the night
    assert row[1]["happened_on"] == "2027-03-02"
    assert (row[2]["created"], row[2]["happened_on"], row[2]["last_time"]) == \
        ("2027-03-01T21:00:00", "2027-03-01", "2027-03-01")
    assert row[10]["happened_on"] == row[9]["happened_on"] == "2027-03-01"  # a correction keeps the day
    assert row[12]["happened_on"] == "2027-03-02"  # the night of 03-01 says 明天
    assert row[13]["happened_on"] == "2027-03-06"  # the date as written, until --dates
    assert conn.execute("SELECT source_memory FROM prospective").fetchone()[0] == 1
    assert {"动物园", "苹果派", "看海", "宿舍"} <= set(json.loads(
        conn.execute("SELECT keys FROM episodes WHERE id = 1").fetchone()[0]))
    assert conn.execute("SELECT 1 FROM relationship WHERE key = 'patterns'").fetchone()
    # nothing that waits for the user was done
    assert row[6]["text"].startswith("他") and row[11]["text"].startswith("他")
    assert row[3]["pact"] is None and row[8]["stability"] == 60.0 and row[11]["stability"] == 90.0
    # and v3 reads it: only the update is "what she used to think"
    store = MemoryStore(conn)
    assert store.former(10).id == 9 and store.former(6) is None and store.former(8) is None


def test_only_what_the_user_named_is_changed(v2):
    mig.run(v2, NOW, apply=True, pacts={3}, subjects={6}, dates="all", ceilings="unasked")
    conn = open_db(v2)
    row = {r["id"]: r for r in conn.execute("SELECT * FROM memories")}
    assert (row[3]["pact"], row[3]["pact_state"], row[3]["about"], row[3]["pinned"]) == ("him", "open", "一辈子", 1)
    assert MemoryStore(conn).pacts()[0].id == 3
    assert row[6]["text"] == "我每晚数米粒，数到五十"
    assert row[11]["text"].startswith("他一直没问成他") and row[11]["stability"] == 14.0
    assert row[8]["stability"] == 60.0  # 待印证 waits for "all"
    assert (row[13]["text"], row[13]["happened_on"]) == ("他2027-03-05周五去面试", "2027-03-05")


def test_a_second_run_finds_nothing_and_keeps_the_first_backup(v2):
    original = contents(v2)
    mig.run(v2, NOW, apply=True, pacts="all", subjects="all", dates="all", ceilings="all")
    migrated = contents(v2)
    steps, saved = mig.run(v2, NOW, apply=True, pacts="all", subjects="all", dates="all", ceilings="all")
    assert saved.name == "fish.db.bak-v2.1"
    assert contents(v2.with_name("fish.db.bak-v2")) == original and contents(saved) == migrated
    assert not any(s.lines for s in steps[:-1]) and not any(s.candidates for s in steps)
    assert step(steps, "9.").lines == ["规律已经数过，不重数"]


def test_nothing_is_written_when_a_step_fails(v2, monkeypatch):
    original = contents(v2)

    def broken(conn, now, step):
        conn.execute("DELETE FROM messages")
        raise RuntimeError("boom")
    monkeypatch.setattr(mig, "count_once", broken)
    with pytest.raises(RuntimeError):
        mig.run(v2, NOW, apply=True)
    conn = open_db(v2)
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM memories WHERE why IS NOT NULL").fetchone()[0] == 0
    assert contents(v2.with_name("fish.db.bak-v2")) == original


def test_a_follow_up_written_by_a_close_finds_the_chat_that_closed(v2):
    """A close run by his next message writes at that message's time: the old chat's end and
    the new chat's start are the same moment, and the follow-up is the old chat's."""
    conn = sqlite3.connect(v2)
    conn.execute("INSERT INTO episodes VALUES (3, '2027-03-04T21:30:00', '2027-03-04T22:00:00',"
                 " '2027-03-05T03:30:00', 'terminal', '', '他说面试的事', '面试', 5, 0, 0)")
    memory(conn, 14, "event", "他周五要去面试", "2027-03-04T21:30:00", ep=2, about="日常", tags=["面试"])
    memory(conn, 15, "event", "他说面试改成线上", "2027-03-04T21:50:00", ep=3, about="日常", tags=["面试"])
    conn.execute("INSERT INTO prospective (id, text, due, created, source_memory, status)"
                 " VALUES (2, '问问他面试顺不顺利', '2027-03-07', '2027-03-04T21:30:00', NULL, 'open')")
    conn.commit()
    conn.close()
    steps, _ = mig.run(v2, NOW, apply=True)
    assert any("惦记 2" in line and "#14 " in line for line in step(steps, "8.").lines)
    conn = open_db(v2)
    assert conn.execute("SELECT source_memory FROM prospective WHERE id = 2").fetchone()[0] == 14

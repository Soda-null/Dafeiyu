"""Her urges (decision 46): the urges to text him, moved out of brain/reach.py unchanged, come
from her memory, her mood and her home, in a fixed order, and only when they are there."""

from datetime import datetime, timedelta

from fish.memory import MemoryStore, ProspectiveStore, Relationship, Window
from fish.mood import Mood
from fish.storage import connect
from fish.urges import HIM, Scene, about_him

NOON = datetime(2026, 10, 28, 12, 0)
CALM = Mood(energy=70, boredom=20, hunger=20)


def wrote(conn, hours_ago: float) -> None:
    Window(conn).append("user", "在吗", "wechat", None, NOON - timedelta(hours=hours_ago))


def test_nothing_going_on_means_no_urge(tmp_path):
    conn = connect(tmp_path / "fish.db")
    wrote(conn, 3)
    Relationship(conn).set("first_met", "2026-10-20")
    assert about_him(Scene(conn, NOON, CALM)) == []


def test_each_source_says_why_in_her_order(tmp_path):
    conn = connect(tmp_path / "fish.db")
    wrote(conn, 20)
    Relationship(conn).set("first_met", "2026-10-22")  # day 7
    seen = MemoryStore(conn).add("world", "候鸟飞得真远", importance=4, source="https://x", now=NOON - timedelta(hours=1))
    MemoryStore(conn).add("world", "不太重要的", importance=2, source="https://y", now=NOON - timedelta(hours=1))
    due = ProspectiveStore(conn).add("问他演示怎么样", "2026-10-28", now=NOON - timedelta(days=2))
    urges = about_him(Scene(conn, NOON, Mood(70, 80, 20), home=("他往冰箱里放了牛奶",)))
    assert [u.source for u in urges] == ["seen", "due", "silence", "anniversary", "bored", "home"]
    assert all(u.about == HIM for u in urges)
    assert urges[0].line == f"今天看到的（见闻 #{seen.id}）：候鸟飞得真远" and urges[0].ref.id == seen.id
    assert urges[1].ref.id == due.id
    assert urges[2].line.endswith("20 个小时没来找你了")
    assert urges[3].ref == 7 and urges[5].line == "家里的事：他往冰箱里放了牛奶"


def test_what_she_already_shared_is_not_an_urge_again(tmp_path):
    conn = connect(tmp_path / "fish.db")
    wrote(conn, 3)
    m = MemoryStore(conn).add("world", "候鸟飞得真远", importance=5, source="https://x", now=NOON - timedelta(hours=1))
    assert [u.source for u in about_him(Scene(conn, NOON, CALM))] == ["seen"]
    assert about_him(Scene(conn, NOON, CALM, shared=frozenset({m.id}))) == []


def test_bored_only_once_he_has_been_quiet_a_while(tmp_path):
    conn = connect(tmp_path / "fish.db")
    wrote(conn, 3)
    bored = Mood(70, 80, 20)
    assert about_him(Scene(conn, NOON, bored)) == []
    assert [u.source for u in about_him(Scene(conn, NOON + timedelta(hours=4), bored))] == ["bored"]

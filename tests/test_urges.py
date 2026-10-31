"""Her urges (decision 46): the urges to text him, moved out of brain/reach.py unchanged, come
from her memory, her mood and her home, in a fixed order, and only when they are there."""

from datetime import datetime, timedelta

from fish.memory import MemoryStore, ProspectiveStore, Relationship, Window
from fish.mood import Mood
from fish.storage import connect
from fish.urges import HIM, Scene, about_doing, about_him, threshold, wanted

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


# --- urges to do things, and the tiers (decision 46, step 2) ---------------------------------

FRESH = {"since": "2026-10-28T08:00"}  # her cottage started keeping track this morning


def wants(conn, now, mood=CALM, been=FRESH):
    return {u.about: u for u in wanted(Scene(conn, now, mood, been=been))}


def test_a_new_place_out_of_the_door_comes_up_a_walk_away_does_not_yet(tmp_path):
    conn = connect(tmp_path / "fish.db")
    got = wants(conn, NOON)
    assert list(got) == ["lake"]  # never been: 0.5 clears the pier (0.4), not the flower shop (0.6)
    assert got["lake"].line == "去湖边码头坐坐：你还没去过湖边码头"
    strength = {u.about: u.strength for u in about_doing(Scene(conn, NOON, CALM, been=FRESH))}
    assert strength == {"lake": 0.5, "florist": 0.5}


def test_days_indoors_push_her_out_and_going_out_settles_it(tmp_path):
    conn = connect(tmp_path / "fish.db")
    later = NOON + timedelta(days=2)
    got = wants(conn, later)
    assert set(got) == {"lake", "florist"}
    assert "你两天没出过门了" in got["florist"].line
    been = FRESH | {"lake": (later - timedelta(hours=2)).isoformat(timespec="minutes")}
    assert wants(conn, later, been=been) == {}  # just back from the pier: neither pulls now
    assert set(wants(conn, later + timedelta(days=3), been=been)) == {"lake", "florist"}  # three days on


def test_tired_or_late_raises_the_bar_for_going_out_only(tmp_path):
    conn = connect(tmp_path / "fish.db")
    tired = Mood(energy=20, boredom=20, hunger=20)
    assert wants(conn, NOON, mood=tired) == {}  # the pier needs 0.6 now
    assert threshold(HIM, Scene(conn, NOON, tired)) == 0.0  # texting him costs nothing more
    assert threshold("lake", Scene(conn, NOON.replace(hour=19), CALM)) == 0.5
    assert wants(conn, NOON, mood=Mood(energy=20, boredom=80, hunger=20))  # bored enough to go anyway


def test_what_she_wrote_she_wants_to_do_pulls(tmp_path):
    conn = connect(tmp_path / "fish.db")
    MemoryStore(conn).add("self", "改天想去花店挑盆绿萝", importance=5, now=NOON - timedelta(days=1))
    got = wants(conn, NOON)
    assert "florist" in got and "你前两天想过：改天想去花店挑盆绿萝" in got["florist"].line
    stale = {u.about: u for u in about_doing(Scene(conn, NOON + timedelta(days=4), CALM, been=FRESH))}
    assert "plan" not in stale["florist"].source  # a plan from long ago has gone stale

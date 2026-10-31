"""The goldfish on her table (decision 43): he gives her one; what it does is drawn by lot, not
made up; she feeds it, changes its water, names it; left alone it sits on the bottom and does
not die."""

import json
from datetime import datetime, timedelta
from pathlib import Path

from fish.brain import FakeLLM
from fish.brain.home_command import home_command
from fish.cottage import Cottage, invented_act
from fish.cottage.tank import HUNGRY, LISTLESS, SWIMMING, clean_name, doing_at

MON = datetime(2026, 11, 2, 10, 0)


def home(tmp_path: Path, now: datetime = MON) -> Cottage:
    c = Cottage(tmp_path / "cottage" / "now.json")
    c.load(now)
    c.advance(now)
    return c


def keys(c: Cottage, now: datetime) -> list[str]:
    return [o.key for o in c.offers(now, hunger=20, energy=70)]


def line(c: Cottage, now: datetime) -> str:
    return c.lines(c.load(now))["tank"]


def test_there_is_no_fish_until_he_gives_one(tmp_path):
    c = home(tmp_path)
    assert "tank" not in c.lines(c.load()) and not {"feed", "change", "namefish"} & set(keys(c, MON))
    said = c.give_fish(MON)
    assert "小鱼缸" in said and "小金鱼" in said
    assert "条小金鱼，还没起名字" in line(c, MON) and "今天喂过了" in line(c, MON)
    assert c.give_fish(MON) == "缸里已经有一条小金鱼了"  # one fish, however many times he says it
    assert sum("小鱼缸" in e["line"] for e in c.load().events) == 1


def test_what_it_does_is_the_lot_for_that_hour_and_the_same_every_time_asked(tmp_path):
    c = home(tmp_path)
    c.give_fish(MON)
    t = c.load().tank
    at = datetime(2026, 11, 2, 14, 0)
    assert doing_at(t, at) == doing_at(t, at) and doing_at(t, at) in SWIMMING
    seen = {doing_at(t, at + timedelta(days=d, hours=h)) for d in range(3) for h in range(5)}
    assert len(seen) > 4  # not always the same thing
    assert doing_at(t, datetime(2026, 11, 3, 2, 0)) == "睡着了，一动不动悬在水里"
    c.advance(MON + timedelta(hours=4))
    assert doing_at(t, datetime(2026, 11, 2, 14, 0)) in line(c, MON + timedelta(hours=4))


def test_feeding_changing_the_water_and_naming_are_hers_and_follow_the_rules(tmp_path):
    c = home(tmp_path)
    c.give_fish(MON)
    assert "feed" not in keys(c, MON) and "change" not in keys(c, MON) and "namefish" in keys(c, MON)
    assert c.act("namefish", MON, "") is None  # a name she has to give
    assert c.act("namefish", MON, "叫豆豆").lines == ["给小金鱼起了名字，叫豆豆"]
    c.advance(MON + timedelta(minutes=5))
    assert "namefish" not in keys(c, MON + timedelta(minutes=5)) and "叫豆豆" in line(c, MON)

    day3 = MON + timedelta(days=1, hours=1)
    c.advance(day3)
    assert "feed" in keys(c, day3) and "change" not in keys(c, day3)
    assert "今天还没喂" in line(c, day3) and doing_at(c.load().tank, day3) in HUNGRY
    assert c.act("feed", day3).lines == ["给豆豆喂了鱼食"]
    c.advance(day3 + timedelta(minutes=5))
    assert "今天喂过了" in line(c, day3) and "feed" not in keys(c, day3 + timedelta(minutes=5))

    later = MON + timedelta(days=3, hours=1)
    c.advance(later)
    assert "水有点浑" in line(c, later) and "change" in keys(c, later)
    assert c.act("change", later).lines == ["给豆豆换了缸里的水"]
    c.advance(later + timedelta(minutes=15))
    assert "水是干净的" in line(c, later)


def test_neglected_it_sits_on_the_bottom_says_so_once_comes_round_and_never_dies(tmp_path):
    c = home(tmp_path)
    c.give_fish(MON)
    t = MON
    for _ in range(9):
        t += timedelta(days=1)
        c.advance(t)
    room = c.load()
    assert room.tank and room.tank["sad"] and doing_at(room.tank, t) in LISTLESS
    said = [e["line"] for e in room.events]
    assert len([x for x in said if "趴在缸底不怎么动了" in x]) <= 3  # said when it turned, not every day
    assert "没喂" in line(c, t)

    c.act("feed", t), c.act("change", t + timedelta(minutes=2))
    c.advance(t + timedelta(minutes=30)), c.act("change", t + timedelta(minutes=30))
    c.advance(t + timedelta(hours=1))
    assert "缓过来了" in " ".join(e["line"] for e in c.load().events)
    assert not c.load().tank.get("sad")


def test_a_couple_of_its_little_doings_go_into_the_record_once_each_and_are_not_news(tmp_path):
    c = home(tmp_path, datetime(2026, 11, 2, 8, 0))
    c.give_fish(datetime(2026, 11, 2, 8, 30))
    day = datetime(2026, 11, 3, 23, 0)
    t = datetime(2026, 11, 2, 8, 30)
    while t < day:
        t += timedelta(minutes=30)
        c.advance(t)
        if "feed" in keys(c, t) and t.hour == 9:
            c.act("feed", t)
    room = c.load()
    moments = [e for e in room.events if e["ts"].startswith("2026-11-03") and e.get("routine") and "小金鱼" in e["line"]
               and "喂" not in e["line"]]
    assert 1 <= len(moments) <= 2 and all(any(m in e["line"] for m in SWIMMING) for e in moments)
    assert not [x for x in c.between(datetime(2026, 11, 3), day, routine=False) if any(m in x for m in SWIMMING)]
    c.advance(day), c.advance(day)
    assert len([e for e in c.load().events if e["ts"].startswith("2026-11-03") and any(m in e["line"] for m in SWIMMING)]) == len(moments)


def test_he_hands_her_the_fish_in_plain_words(tmp_path):
    c = home(tmp_path)
    reply = json.dumps({"ops": [{"op": "put", "where": "tank", "what": "小金鱼"}], "say": ""}, ensure_ascii=False)
    out = home_command(FakeLLM(lambda m, j: reply), c, "给她养条小鱼", MON)
    assert out and "小金鱼" in out[0] and c.load().tank
    again = home_command(FakeLLM(lambda m, j: reply), c, "再送她一条", MON)
    assert again == ["缸里已经有一条小金鱼了"]
    take = json.dumps({"ops": [{"op": "take", "where": "tank", "what": "小金鱼"}], "say": "不能拿走小鱼"}, ensure_ascii=False)
    assert home_command(FakeLLM(lambda m, j: take), c, "把鱼拿走", MON) == ["不能拿走小鱼"] and c.load().tank


def test_names_and_what_she_cannot_write_herself(tmp_path):
    assert clean_name("起名叫豆豆") == "豆豆" and clean_name("“小肥”") == "小肥" and clean_name("") == ""
    assert clean_name("一个特别特别长的名字") == ""
    assert invented_act("喂了小鱼") and not invented_act("想去喂小鱼")
    c = home(tmp_path)
    c.give_fish(MON)
    assert "小金鱼" in c.for_chat(MON, 20)  # a fish that has just come is worth a line in a chat

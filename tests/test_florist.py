"""The flower shop in town and her flowers on the windowsill (decision 45): fifteen minutes'
walk, closed on Mondays, what is in season; on the sill only once she is home; watered with her
pots, they keep; left dry they droop, then die."""

from datetime import datetime, timedelta
from pathlib import Path

from fish.cottage import Cottage
from fish.cottage.rules import FLOWER_SPOTS, FLOWERS, flowers_in_stock

MON = datetime(2026, 11, 2, 10, 0)
TUE = MON + timedelta(days=1)


def home(tmp_path: Path, now: datetime = TUE) -> Cottage:
    c = Cottage(tmp_path / "cottage" / "now.json")
    c.load(now)
    c.advance(now)
    return c


def keys(c: Cottage, now: datetime) -> list[str]:
    return [o.key for o in c.offers(now, hunger=20, energy=70)]


def buy(c: Cottage, now: datetime, what: str) -> datetime:
    assert c.act("florist", now, what) is not None
    back = now + timedelta(minutes=41)
    c.advance(back)
    return back


def test_closed_on_mondays_and_out_of_hours(tmp_path):
    c = home(tmp_path, MON)
    assert "florist" not in keys(c, MON)
    assert c.act("florist", MON, "绿萝") is None
    assert "florist" in keys(c, TUE)
    assert "florist" not in keys(c, TUE.replace(hour=17, minute=50))  # shut by the time she gets there


def test_it_sells_what_is_in_season():
    assert flowers_in_stock(datetime(2026, 11, 3, 10)) == ["绿萝", "多肉", "小菊花"]
    assert "水仙" in flowers_in_stock(datetime(2027, 1, 5, 10))
    assert all(n in FLOWERS for m in range(1, 13) for n in flowers_in_stock(datetime(2026, m, 3, 10)))


def test_what_she_buys_is_on_the_sill_only_once_she_is_home(tmp_path):
    c = home(tmp_path)
    assert c.act("florist", TUE, "菊花、玫瑰").lines == ["出门去镇上的花店（想买菊花、玫瑰）"]
    room = c.load(TUE)
    assert c.doing_line(room, now=TUE + timedelta(minutes=5)).startswith("你在去镇上花店的路上")
    assert c.doing_line(room, now=TUE + timedelta(minutes=20)).startswith("你在花店里挑花")
    assert c.doing_line(room, now=TUE + timedelta(minutes=30)).startswith("你抱着小菊花往回走")
    c.advance(TUE + timedelta(minutes=30))
    assert c.load(TUE + timedelta(minutes=30)).flowers == []  # still on the way
    back = c.advance(TUE + timedelta(minutes=41))
    assert back.lines == ["从花店回来了，买了小菊花，摆在窗台上，浇了水（想要的玫瑰没有）"]
    room = c.load(TUE + timedelta(minutes=41))
    assert [f["name"] for f in room.flowers] == ["小菊花"]
    assert c.lines(room)["flowers"] == "窗台上你自己买的花：小菊花（今天浇过水）"
    assert c.lines(room)["sill"] == "窗台上除了你的花没别的"  # not "窗台空着" beside them


def test_the_sill_holds_only_so_many(tmp_path):
    c = home(tmp_path)
    back = buy(c, TUE, "绿萝、多肉、小菊花、绿萝")
    assert len(c.load(back).flowers) == FLOWER_SPOTS
    assert "florist" not in keys(c, back + timedelta(hours=3))  # no room left


def test_watered_with_her_pots_left_dry_they_droop_then_die(tmp_path):
    c = home(tmp_path)
    buy(c, TUE, "小菊花")
    day = lambda n: datetime.combine((TUE + timedelta(days=n)).date(), TUE.time())  # noqa: E731
    c.advance(day(1))
    water = next(o for o in c.offers(day(1), hunger=20, energy=70) if o.key == "water")
    assert water.line == "给窗台上的小菊花浇水"
    assert c.act("water", day(1)).lines == ["给小菊花浇了水"]
    c.advance(day(1) + timedelta(minutes=5))
    assert "窗台上的小菊花三天没浇水，蔫了" in c.advance(day(4)).lines
    assert c.lines(c.load(day(4)))["flowers"].startswith("窗台上你自己买的花：小菊花（蔫了，")
    c.act("water", day(4))
    assert "窗台上的小菊花浇了水，缓过来了" in c.advance(day(4) + timedelta(minutes=5)).lines
    assert "窗台上的小菊花6天没浇水，干死了，只好扔了" in c.advance(day(10)).lines
    assert c.load(day(10)).flowers == []

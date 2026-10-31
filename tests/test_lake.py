"""The little pier outside her door (decision 45): she sits there half an hour, and what she saw
is drawn by lot, not made up."""

from datetime import datetime, timedelta
from pathlib import Path

from fish.cottage import Cottage
from fish.cottage.lake import SIGHTS, sight

TUE = datetime(2026, 11, 3, 15, 0)


def home(tmp_path: Path, now: datetime = TUE) -> Cottage:
    c = Cottage(tmp_path / "cottage" / "now.json")
    c.load(now)
    c.advance(now)
    return c


def keys(c: Cottage, now: datetime) -> list[str]:
    return [o.key for o in c.offers(now, hunger=20, energy=70)]


def test_she_sits_on_the_pier_and_comes_back_with_what_she_saw(tmp_path):
    c = home(tmp_path)
    assert "lake" in keys(c, TUE)
    change = c.act("lake", TUE)
    assert change.lines == ["出门去湖边码头坐一会儿"]
    room = c.load(TUE)
    assert c.doing_line(room, now=TUE) == "你这会儿在湖边码头坐着，大概到 15:30"
    assert keys(c, TUE + timedelta(minutes=5)) == []  # busy: nothing else starts
    back = c.advance(TUE + timedelta(minutes=31))
    line = back.lines[0]
    assert line.startswith("从湖边码头回来了，坐了半个钟头，看见")
    assert any(s in line for s in SIGHTS)
    assert c.load(TUE + timedelta(minutes=31)).doing == ""


def test_what_she_sees_is_the_same_lot_for_the_same_hour():
    at = datetime(2026, 11, 3, 15, 10)
    assert sight(at) == sight(at.replace(minute=50))
    assert {sight(datetime(2026, 11, d, 15)) for d in range(1, 30)} <= set(SIGHTS)


def test_not_again_right_away_and_not_after_dark(tmp_path):
    c = home(tmp_path)
    c.act("lake", TUE)
    c.advance(TUE + timedelta(minutes=31))
    assert "lake" not in keys(c, TUE + timedelta(minutes=40))
    assert "lake" in keys(c, TUE + timedelta(hours=3))
    assert c.act("lake", datetime(2026, 11, 3, 19, 45)) is None  # back after 20:00: too dark
    assert "lake" not in keys(c, datetime(2026, 11, 3, 20, 30))

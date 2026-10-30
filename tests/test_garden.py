"""Her windowsill pots (decision 42): she sows, waters and picks; time grows them a morning at a
time, a dry pot wilts and then dies, and what she picks is food in the fridge."""

import json
from datetime import datetime, timedelta
from pathlib import Path

from fish.cottage import Cottage, invented_act, layout
from fish.cottage.rules import DIE_DAYS, PLANTS, WILT_DAYS

MON = datetime(2026, 11, 2, 10, 0)


def home(tmp_path: Path, now: datetime = MON) -> Cottage:
    c = Cottage(tmp_path / "cottage" / "now.json")
    c.load(now)
    c.advance(now)
    return c


def keys(c: Cottage, now: datetime) -> list[str]:
    return [o.key for o in c.offers(now, hunger=20, energy=70)]


def days_on(c: Cottage, start: datetime, n: int, *, water: bool = True) -> datetime:
    """n mornings later, watering each day at ten when asked to."""
    t = start
    for _ in range(n):
        t = t + timedelta(days=1)
        c.advance(t)
        if water and "water" in keys(c, t):
            assert c.act("water", t) is not None
            c.advance(t + timedelta(minutes=5))
    return t


def test_the_pots_start_empty_and_she_can_sow_what_she_has_seeds_of(tmp_path):
    c = home(tmp_path)
    assert "花盆" in layout() and "种子" in layout()
    assert c.lines(c.load())["pots"] == "窗台上的花盆都空着"
    assert "sow" in keys(c, MON) and "water" not in keys(c, MON)
    assert c.act("sow", MON, "种点辣椒") is None  # no seeds of that
    change = c.act("sow", MON, "种点葱吧")
    assert change.lines == ["在窗台的花盆里种下了小葱，浇了水"]
    c.advance(MON + timedelta(minutes=15))
    assert c.lines(c.load())["pots"] == "窗台上的花盆：小葱（种下第 1 天，还没出芽，还要长 14 天才能剪，现在没得吃，今天浇过水）；还空着一个"
    assert "water" not in keys(c, MON + timedelta(minutes=15))  # watered when sown


def test_watered_it_sprouts_in_the_morning_and_she_sees_it(tmp_path):
    c = home(tmp_path)
    c.act("sow", MON, "小葱")
    t = days_on(c, MON, 3)
    room = c.load()
    assert any(e["line"] == "小葱冒芽了" and e["ts"].endswith("08:00") for e in room.events)
    assert "冒芽了" in c.lines(room)["pots"]
    assert "小葱冒芽了" in c.between(t - timedelta(days=1), t, routine=False)[0]  # news: a reason to text him
    assert not any("浇了水" in x for x in c.between(MON, t, routine=False))  # watering is not news


def test_left_dry_it_wilts_stops_growing_comes_round_or_dies(tmp_path):
    c = home(tmp_path)
    c.act("sow", MON, "小白菜")
    t = days_on(c, MON, WILT_DAYS, water=False)
    room = c.load()
    assert room.pots[0]["wilted"] and room.pots[0]["days"] == WILT_DAYS - 1
    assert "蔫了" in c.lines(room)["pots"] and "蔫了" in c.for_chat(t, 20)  # a drooping pot is shown in a chat
    c.act("water", t)
    t = days_on(c, t, 1)
    assert "小白菜缓过来了" in [e["line"] for e in c.load().events]
    assert not c.load().pots[0].get("wilted")

    c2 = home(tmp_path / "b")
    c2.act("sow", MON, "番茄")
    days_on(c2, MON, DIE_DAYS, water=False)
    room = c2.load()
    assert room.pots[0] == {} and any("干死了" in e["line"] for e in room.events)


def test_spring_onions_are_cut_into_the_fridge_and_grow_back(tmp_path):
    c = home(tmp_path)
    c.act("sow", MON, "小葱")
    onion = PLANTS["小葱"]
    t = days_on(c, MON, onion.ripe_at)
    assert "小葱能剪了" in [e["line"] for e in c.load().events]
    assert "pick" in keys(c, t) and "能剪了" in c.for_chat(t, 20)
    change = c.act("pick", t)
    assert change.lines == ["剪了一把小葱，放进冰箱"]
    room = c.load()
    assert any(i["name"] == "小葱" for i in room.fridge) and room.pots[0]["plant"] == "小葱"
    assert "pick" not in keys(c, t + timedelta(minutes=10))
    days_on(c, t, onion.again)
    assert "小葱又长起来了，能剪了" in [e["line"] for e in c.load().events]


def test_greens_are_picked_once_and_the_pot_is_free_again(tmp_path):
    c = home(tmp_path)
    c.act("sow", MON, "白菜")
    t = days_on(c, MON, PLANTS["小白菜"].ripe_at)
    assert c.act("pick", t).lines == ["摘了小白菜（花盆空出来了），放进冰箱"]
    room = c.load()
    assert room.pots == [{}, {}] and next(i for i in room.fridge if i["name"] == "小白菜")["meals"] == 2


def test_what_she_picked_she_can_cook_or_leave_him(tmp_path):
    c = home(tmp_path)
    c.act("sow", MON, "葱")
    t = days_on(c, MON, PLANTS["小葱"].ripe_at)
    c.act("pick", t)
    later = t + timedelta(minutes=10)
    c.advance(later)
    assert c.act("leave", later, "小葱") is not None
    assert "小葱（给他留的" in c.lines(c.load())["sill"]


def test_both_pots_and_a_room_from_before_the_pots(tmp_path):
    c = home(tmp_path)
    data = json.loads(c.path.read_text(encoding="utf-8"))
    data.pop("pots"), data.pop("grew")  # a now.json written before decision 42
    c.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    c.advance(MON + timedelta(days=1))
    assert c.load().pots == [{}, {}]
    t = MON + timedelta(days=1, minutes=5)
    c.act("sow", t, "小葱")
    c.advance(t + timedelta(minutes=15))
    c.act("sow", t + timedelta(minutes=15), "小番茄")
    c.advance(t + timedelta(minutes=30))
    assert "sow" not in keys(c, t + timedelta(minutes=30))  # no empty pot left
    assert "给窗台上的小葱、小番茄浇水" in [o.line for o in c.offers(t + timedelta(days=1, hours=2), 20, 70)]


def test_she_cannot_write_herself_into_having_watered_or_picked():
    assert invented_act("给小葱浇了水") and invented_act("摘了两颗番茄")
    assert not invented_act("想去浇个水")

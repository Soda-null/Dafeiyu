"""The numbers of her cottage (decision 26). docs/cottage_rules_zh.md is the readable copy:
change a number there and here together. The layout itself is read from that file."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, time

from fish.config import REPO_ROOT

RULES_PATH = REPO_ROOT / "docs" / "cottage_rules_zh.md"

RICE_FULL = 12  # meals in a full rice jar
FRIDGE_SLOTS = 8  # kinds of things the fridge holds
CARRY = 5  # kinds of things she can carry home from one trip
SINK_LIMIT = 3  # more unwashed than this and she washes up before cooking
HUNGRY = 50  # cooking is on her menu from here
TIRED = 50  # a nap is on her menu below this
HUNGER_PER_HOUR = 3.0  # awake hours make her hungry; eating is what undoes it
ENERGY_PER_HOUR = 2.5  # awake hours tire her; a nap or the night's sleep is what undoes it
SLEEP_FROM, WAKE_AT = time(0, 0), time(8, 0)
MEALS = (("午饭", time(11, 30), time(13, 30)), ("晚饭", time(17, 30), time(19, 30)))
ATE_RECENTLY_HOURS = 2.5  # a meal she cooked herself this close to mealtime counts as that meal


@dataclass(frozen=True)
class Action:
    key: str
    doing: str  # "做饭": what she is doing while it lasts
    minutes: int
    hunger: float = 0.0
    energy: float = 0.0


ACTIONS = {a.key: a for a in (
    Action("rice", "煮白饭", 30, hunger=-35),
    Action("cook", "做饭", 40, hunger=-50, energy=-5),
    Action("wash", "洗碗", 10, energy=-3),
    Action("bed", "叠被子", 2),
    Action("nap", "睡午觉", 60, energy=25),
    Action("shop", "去菜店", 30, energy=-8),
    Action("leave", "给他留东西", 1),  # something from the fridge, or a note, onto the windowsill for him
    Action("sow", "种东西", 10),  # her windowsill pots (decision 42, garden.py)
    Action("water", "浇水", 3),
    Action("pick", "摘菜", 5),
    Action("feed", "喂小金鱼", 1),  # her goldfish on the table (decision 43, tank.py)
    Action("change", "给鱼缸换水", 10, energy=-2),
    Action("namefish", "给小金鱼起名字", 1),
    Action("lake", "湖边码头坐着", 30),  # out of the door and she is there (decision 45, lake.py)
    Action("florist", "去花店", 40, energy=-10),  # fifteen minutes each way, ten inside (florist.py)
)}
NOTE_PREFIX = "纸条"  # "纸条：早点睡" is a note she writes; anything else she leaves must be in the fridge


@dataclass(frozen=True)
class Good:
    name: str
    meals: int  # how many meals one purchase lasts
    keeps_days: int | None  # None: never goes off


GOODS = {g.name: g for g in (
    Good("鸡蛋", 3, 14), Good("青菜", 1, 3), Good("豆腐", 1, 3), Good("肉", 2, 3),
    Good("西红柿", 2, 7), Good("土豆", 2, 7), Good("南瓜", 3, 14), Good("萝卜", 2, 14),
    Good("小葱", 1, 5), Good("小白菜", 2, 3), Good("小番茄", 1, 7),  # from her pots, never sold
)}
RICE = "米"


@dataclass(frozen=True)
class Plant:
    """What grows in her pots (decision 42). Days count only days it was watered enough."""
    name: str
    also: tuple[str, ...]  # other words for it ("葱", "西红柿")
    stages: tuple[tuple[int, str], ...]  # (growing days, what she sees that morning)
    ripe_at: int  # growing days until the first picking
    ready_words: str  # "能剪了"
    meals: int  # what one picking puts in the fridge
    again: int | None = None  # days until the next picking; None: picked once, the pot is empty
    again_words: str = ""
    cut: bool = False  # cut down when picked and grows back (spring onions), not picked off the plant


PLANTS = {p.name: p for p in (
    Plant("小葱", ("葱",), ((3, "冒芽了"), (8, "长到一指高了")), 14, "能剪了", 1,
          again=7, again_words="又长起来了，能剪了", cut=True),
    Plant("小白菜", ("白菜", "青菜"), ((3, "冒芽了"), (10, "长出四片叶子了")), 25, "能摘了", 2),
    Plant("小番茄", ("番茄", "西红柿"), ((6, "冒芽了"), (20, "长到一尺高了"), (35, "开小黄花了"), (50, "结了青果子")),
          60, "第一颗红了", 1, again=3, again_words="又红了一颗"),
)}
POTS = 2  # on the windowsill
RIPE_AT_MOST = 6  # ripe ones waiting on one plant; spring onions are cut once ready
WILT_DAYS, DIE_DAYS = 3, 6  # this many days without water: it wilts and stops growing; it dies

FISH_KIND = "小金鱼"
FISH_DIRTY_DAYS, FISH_FOUL_DAYS = 3, 7  # days since the water was changed: cloudy; so bad it sits on the bottom
FISH_LISTLESS_DAYS = 2  # days unfed: it sits on the bottom (it never dies: decision 43)
FISH_MOMENTS = 2  # little things it does each day that go into the room's record
SHOP_OPEN, SHOP_CLOSE = time(7, 0), time(19, 0)
SHOP_REST_WEEKDAY = 1  # Tuesday
SHOP_WALK_MINUTES = 10
SHOP_AGAIN_HOURS = 2  # just back from the shop, she does not go again (10-29 trial: back at 09:23, out at 09:30)
GREENS_GONE_AFTER = time(15, 0)
EVERY_DAY = ("鸡蛋", "青菜", "豆腐", "肉", "西红柿", "土豆")
IN_SEASON = {9: "南瓜", 10: "南瓜", 11: "南瓜", 12: "萝卜", 1: "萝卜", 2: "萝卜"}

LAKE_UNTIL = time(20, 0)  # after dark she stays in (decision 45)
LAKE_AGAIN_HOURS = 2


@dataclass(frozen=True)
class Flower:
    """A small potted plant from the flower shop, for her windowsill (decision 45). It does not
    grow; watered it keeps, left dry `wilt_days` it droops, twice that it dies."""
    name: str
    also: tuple[str, ...]
    wilt_days: int


FLOWERS = {f.name: f for f in (
    Flower("绿萝", (), 5), Flower("多肉", ("肉肉",), 10),
    Flower("风信子", (), 3), Flower("茉莉", ("茉莉花",), 3), Flower("栀子", ("栀子花",), 3),
    Flower("小菊花", ("菊花",), 3), Flower("桂花", (), 4), Flower("水仙", ("水仙花",), 3), Flower("仙客来", (), 4),
)}
FLOWERS_ALWAYS = ("绿萝", "多肉")
FLOWERS_IN_SEASON = {3: ("风信子",), 4: ("风信子",), 5: ("茉莉",), 6: ("茉莉", "栀子"), 7: ("茉莉", "栀子"),
                     8: ("茉莉",), 9: ("桂花",), 10: ("小菊花", "桂花"), 11: ("小菊花",), 12: ("仙客来",),
                     1: ("水仙", "仙客来"), 2: ("水仙",)}
FLOWER_SPOTS = 3  # her own flowers on the sill, beside the pots and his tank
FLORIST_OPEN, FLORIST_CLOSE = time(9, 0), time(18, 0)
FLORIST_REST_WEEKDAY = 0  # Monday
FLORIST_WALK_MINUTES = 15
FLORIST_AGAIN_HOURS = 2


def florist_open(now: datetime) -> bool:
    return now.weekday() != FLORIST_REST_WEEKDAY and FLORIST_OPEN <= now.time() < FLORIST_CLOSE


def flowers_in_stock(now: datetime) -> list[str]:
    return list(FLOWERS_ALWAYS) + list(FLOWERS_IN_SEASON.get(now.month, ()))


def shop_open(now: datetime) -> bool:
    return now.weekday() != SHOP_REST_WEEKDAY and SHOP_OPEN <= now.time() < SHOP_CLOSE


def in_stock(now: datetime) -> list[str]:
    """What the shop has right now: rice always; one thing missing each day, the same all
    day; greens gone in the afternoon; something in season."""
    goods = list(EVERY_DAY) + ([IN_SEASON[now.month]] if now.month in IN_SEASON else [])
    goods.remove(random.Random(now.date().toordinal()).choice(goods))
    if now.time() >= GREENS_GONE_AFTER and "青菜" in goods:
        goods.remove("青菜")
    return [RICE] + goods


def mealtime(now: datetime) -> str | None:
    return next((name for name, start, end in MEALS if start <= now.time() < end), None)


def asleep_hours(t: datetime) -> bool:
    return SLEEP_FROM <= t.time() < WAKE_AT


SUMMARY_MARK = "**一句话给她：**"


def _section_one(path) -> list[str]:
    lines, inside = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            inside = line.startswith("## 1.")
            continue
        if inside:
            lines.append(line)
    return lines


def layout(path=RULES_PATH) -> str:
    """The room as she is told it when she decides what to do: the bullets of §1 of the
    rules file, without the markup."""
    return "\n".join(line[2:].replace("**", "").replace("： ", "：")
                     for line in _section_one(path) if line.startswith("- "))


def summary(path=RULES_PATH) -> str:
    """One line for every chat turn: the layout costs more than it tells there."""
    return next((line[len(SUMMARY_MARK):].strip() for line in _section_one(path) if line.startswith(SUMMARY_MARK)), "")

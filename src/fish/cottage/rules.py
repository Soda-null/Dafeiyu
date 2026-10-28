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
)}


@dataclass(frozen=True)
class Good:
    name: str
    meals: int  # how many meals one purchase lasts
    keeps_days: int | None  # None: never goes off


GOODS = {g.name: g for g in (
    Good("鸡蛋", 3, 14), Good("青菜", 1, 3), Good("豆腐", 1, 3), Good("肉", 2, 3),
    Good("西红柿", 2, 7), Good("土豆", 2, 7), Good("南瓜", 3, 14), Good("萝卜", 2, 14),
)}
RICE = "米"
SHOP_OPEN, SHOP_CLOSE = time(7, 0), time(19, 0)
SHOP_REST_WEEKDAY = 1  # Tuesday
SHOP_WALK_MINUTES = 10
GREENS_GONE_AFTER = time(15, 0)
EVERY_DAY = ("鸡蛋", "青菜", "豆腐", "肉", "西红柿", "土豆")
IN_SEASON = {9: "南瓜", 10: "南瓜", 11: "南瓜", 12: "萝卜", 1: "萝卜", 2: "萝卜"}


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

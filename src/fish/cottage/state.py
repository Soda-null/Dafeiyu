"""What her room is made of (decision 26): the record kept in data/cottage/now.json, what one
step of time or one action did to it, and the small rules every part of the cottage shares."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from fish.cottage.rules import FRIDGE_SLOTS, GOODS, POTS, RICE_FULL, SINK_LIMIT, Good

KEEP_EVENTS = timedelta(days=2)
# What she may not write about herself once she has a room: things done to it. Doing, buying
# and eating happen through the rules and are in `events`; her own notes keep thoughts and
# plans. Wanting to ("想做饭", "打算去买") is a thought and passes.
INVENTED_ACT = re.compile(r"(?<![想要打算准备])(做|煮|炒|烧|吃|买|洗|叠|收拾|打扫|种|养|浇|摘|剪|喂|睡|躺|煎|炖|蒸)(了|过|完|着|好)")
KEEP_MEALS = 6
COUNT_WORDS = {2: "两", 3: "三", 4: "四", 5: "五"}
BED_WORDS = {"叠好": "被子叠好了", "乱": "被子没叠", "在睡": "你在床上"}
SPLIT = re.compile(r"[、，,；;\s]+|和")


def invented_act(text: str) -> bool:
    """True when a note of hers says she did something to the room ("煮了面", "买了盆花")."""
    return INVENTED_ACT.search(text) is not None


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="minutes")


@dataclass
class Room:
    doing: str = ""  # what she is busy with ("做饭", "睡觉"), "" when nothing in particular
    until: str = ""  # when that ends; empty for sleep, which ends at WAKE_AT
    bed: str = "叠好"  # 叠好 / 乱 / 在睡
    fridge: list[dict] = field(default_factory=list)  # {"name": "鸡蛋", "meals": 3, "bought": "2026-10-28"}
    rice: int = RICE_FULL // 2  # meals left in the rice jar
    sink: list[str] = field(default_factory=list)  # what is waiting to be washed
    sill: list[str] = field(default_factory=list)  # on the windowsill: his presents, and what she left him
    meals: list[str] = field(default_factory=list)  # "2026-10-28 午饭": that mealtime is done with
    ate: str = ""  # when she last ate
    pending: dict = field(default_factory=dict)  # what comes at `until`: a meal ({"hunger", "line"}) or the shopping ({"buy"})
    guest: dict = field(default_factory=dict)  # him at her place: {"since", "until", "why", "here"} (decision 41)
    pots: list[dict] = field(default_factory=lambda: [{} for _ in range(POTS)])  # her windowsill pots (decision 42)
    grew: str = ""  # the last morning the pots grew
    tank: dict = field(default_factory=dict)  # her goldfish: {"name", "since", "from", "fed", "water"} (decision 43)
    events: list[dict] = field(default_factory=list)  # {"ts", "line"}, the last two days
    last: str = ""  # up to when time has moved the room


@dataclass
class Change:
    """What one step did: lines for her day, and how it moves her hunger and energy."""
    lines: list[str] = field(default_factory=list)
    hunger: float = 0.0
    energy: float = 0.0
    ate: list[tuple[datetime, float]] = field(default_factory=list)  # (when, hunger it took off)
    slept: list[tuple[datetime, datetime]] = field(default_factory=list)  # (from, to): a nap or the night

    def __iadd__(self, other: "Change") -> "Change":
        self.lines += other.lines
        self.hunger += other.hunger
        self.energy += other.energy
        self.ate += other.ate
        self.slept += other.slept
        return self


@dataclass(frozen=True)
class Offer:
    key: str
    line: str
    arg_hint: str = ""


def fresh(now: datetime) -> Room:
    today = now.date().isoformat()
    return Room(fridge=[{"name": "鸡蛋", "meals": 3, "bought": today}, {"name": "青菜", "meals": 1, "bought": today}],
                last=now.isoformat(timespec="seconds"))


def rice_word(rice: int) -> str:
    return "满的" if rice >= 8 else "还有一半" if rice >= 4 else "快见底了" if rice >= 1 else "空了"


def can_cook(room: Room) -> bool:
    return room.rice > 0 and bool(room.fridge) and len(room.sink) <= SINK_LIMIT


def sill_name(item: str) -> str:
    """"小葱（给他留的，10-29）" -> "小葱"."""
    return item.split("（")[0]


def _good(name: str) -> Good:
    return GOODS.get(name, Good(name, 1, None))  # something he put in that the shop does not sell


def _days_left(item: dict, today: date) -> float:
    good = _good(item["name"])
    if good.keeps_days is None:
        return float("inf")
    return good.keeps_days - (today - date.fromisoformat(item["bought"])).days


def put_in(room: Room, name: str, now: datetime, meals: int | None) -> bool:
    """Into the fridge. False when it is full and holds none of this already."""
    today = now.date().isoformat()
    same = next((i for i in room.fridge if i["name"] == name and i["bought"] == today), None)
    if name not in {i["name"] for i in room.fridge} and len({i["name"] for i in room.fridge}) >= FRIDGE_SLOTS:
        return False
    add = meals if meals is not None else _good(name).meals
    if same is not None:
        same["meals"] += add
    else:
        room.fridge.append({"name": name, "meals": add, "bought": today})
    return True

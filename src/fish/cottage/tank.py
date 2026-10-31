"""The goldfish in her tank (decisions 43, 44): he puts one into the tank he gave her on the
windowsill (a small tank comes with it only when there is none). What it does is
drawn by lot from a short list, the same lot for the same hour of the same day, so it is
nobody's to make up: she sees it in the room's lines and cannot write "it did a flip". She
feeds it once a day and changes its water now and then, and names it. Left alone it sits on
the bottom; it never dies. A few of its little doings go into the room's record, so the diary
and the night's letter have them."""

from __future__ import annotations

import random
import re
from datetime import date, datetime

from fish.config import owner_words
from fish.cottage.rules import (FISH_DIRTY_DAYS, FISH_FOUL_DAYS, FISH_KIND, FISH_LISTLESS_DAYS, FISH_MOMENTS,
                                asleep_hours)
from fish.cottage.state import Change, Offer, Room

KEYS = ("feed", "change", "namefish")
NAME_MAX = 6
AWAKE_HOURS = range(9, 23)  # its little doings are noted in these hours
SWIMMING = ("在缸里慢悠悠地游", "追着自己的影子转圈", "吐了一串泡泡", "躲在水草后面不出来", "贴着玻璃朝外看",
            "在缸底的沙子里拱来拱去", "浮在水面上一张一合地张嘴", "一动不动悬在水中间发呆", "猛地窜了半个缸又停下",
            "绕着小石头游了一圈又一圈")
HUNGRY = ("在水面上绕圈，等着有人撒鱼食", "贴着玻璃上下游，像是在要吃的")
LISTLESS = ("趴在缸底，不怎么动", "缩在水草边上，鳍都耷拉着")
ASLEEP = "睡着了，一动不动悬在水里"
NAME_PREFIX = re.compile(r"^(起个?名(字)?叫?|名字叫|叫)")
NOISE = re.compile(r"[\s「」“”\"'，。,.！!：:]")


def clean_name(arg: str) -> str:
    """"叫豆豆" -> "豆豆"; "" when there is nothing usable (empty, or longer than a name)."""
    text = NAME_PREFIX.sub("", NOISE.sub("", arg))
    return text if 1 <= len(text) <= NAME_MAX else ""


def _days(stamp: str, today: date) -> int:
    return (today - date.fromisoformat(stamp)).days


def who(tank: dict) -> str:
    return tank.get("name") or FISH_KIND


def listless(tank: dict, today: date) -> bool:
    return _days(tank["fed"], today) >= FISH_LISTLESS_DAYS or _days(tank["water"], today) >= FISH_FOUL_DAYS


def doing_at(tank: dict, at: datetime) -> str:
    """What it is doing in that hour: by lot, the same answer however often it is asked."""
    if asleep_hours(at):
        return ASLEEP
    pool = SWIMMING
    if listless(tank, at.date()):
        pool = LISTLESS
    elif _days(tank["fed"], at.date()) >= 1 and at.hour >= 10:  # not fed yet today
        pool = HUNGRY
    return random.Random(f"{at.date().isoformat()}-{at.hour}-{tank['since']}").choice(pool)


def moment_hours(tank: dict, day: date) -> list[int]:
    return sorted(random.Random(f"moments-{day.isoformat()}-{tank['since']}").sample(AWAKE_HOURS, FISH_MOMENTS))


class TankMixin:
    """Part of Cottage (room.py): the goldfish. Uses the room's load / save / note."""

    def give_fish(self, now: datetime) -> str:
        """He puts a goldfish into the tank on her windowsill (decision 44: he had given her a big
        one on 10-28; a small one comes with the fish only when there is none). One fish: a
        second is refused."""
        room = self.load(now)
        if room.tank:
            return f"缸里已经有一条{FISH_KIND}了"
        today = now.date().isoformat()
        room.tank = {"name": "", "since": today, "from": now.isoformat(timespec="minutes"), "fed": today, "water": today}
        if any("鱼缸" in i for i in room.sill):
            line = owner_words(f"他往窗台上的鱼缸里放了一条{FISH_KIND}")
        else:
            room.sill.append(owner_words(f"一个小鱼缸（他 {now.month}-{now.day} 送的）"))
            line = owner_words(f"他送来一个小鱼缸和一条{FISH_KIND}，放在窗台上")
        self.note(room, now, line)
        self.save(room)
        return line

    @staticmethod
    def tank_holds(room: Room, item: str) -> bool:
        """The tank on the sill cannot be taken away while the fish is in it."""
        return bool(room.tank) and "鱼缸" in item

    @staticmethod
    def tank_offers(room: Room, now: datetime) -> list[Offer]:
        t = room.tank
        if not t:
            return []
        out = []
        if t["fed"] != now.date().isoformat():
            out.append(Offer("feed", f"给{who(t)}喂点鱼食"))
        if _days(t["water"], now.date()) >= FISH_DIRTY_DAYS:
            out.append(Offer("change", f"给{who(t)}的鱼缸换水"))
        if not t.get("name"):
            out.append(Offer("namefish", f"给{FISH_KIND}起个名字", "起什么名字，两到四个字"))
        return out

    def tank_possible(self, room: Room, key: str, now: datetime, arg: str) -> bool:
        return any(o.key == key for o in self.tank_offers(room, now)) and (key != "namefish" or bool(clean_name(arg)))

    @staticmethod
    def _tank_apply(room: Room, key: str, now: datetime, arg: str) -> str:
        t, today = room.tank, now.date().isoformat()
        if key == "feed":
            t["fed"] = today
            return f"给{who(t)}喂了鱼食"
        if key == "change":
            t["water"] = today
            return f"给{who(t)}换了缸里的水"
        t["name"] = clean_name(arg)
        return f"给{FISH_KIND}起了名字，叫{t['name']}"

    def _tank_step(self, room: Room, now: datetime, change: Change) -> None:
        """When it turns listless (or comes round) the record says so once; on a day it is
        fed and well, a couple of its little doings are put in the record."""
        t = room.tank
        if not t or asleep_hours(now):
            return
        sad, name = listless(t, now.date()), who(t)
        if sad and not t.get("sad"):
            t["sad"] = True
            unfed = _days(t["fed"], now.date())
            why = f"{unfed}天没喂" if unfed >= FISH_LISTLESS_DAYS else f"水{_days(t['water'], now.date())}天没换，浑得厉害"
            self.note(room, now, f"{name}{why}，趴在缸底不怎么动了", change)
        elif not sad and t.pop("sad", False):
            self.note(room, now, f"{name}缓过来了，又游起来了", change)
        if sad or _days(t["fed"], now.date()) != 0:
            return
        noted = t.setdefault("noted", [])
        for hour in moment_hours(t, now.date()):
            at, key = datetime.combine(now.date(), datetime.min.time()).replace(hour=hour), f"{now.date().isoformat()}-{hour}"
            if at <= now and at >= datetime.fromisoformat(t["from"]) and key not in noted:
                noted.append(key)
                self.note(room, at, f"{name}{doing_at(t, at)}", change, routine=True)
        t["noted"] = noted[-6:]

    @staticmethod
    def tank_line(room: Room) -> str:
        t = room.tank
        if not t:
            return ""
        at = datetime.fromisoformat(room.last) if room.last else datetime.now()
        fed = _days(t["fed"], at.date())
        water = _days(t["water"], at.date())
        eaten = "今天喂过了" if fed == 0 else "今天还没喂" if fed == 1 else f"{fed}天没喂了"
        clean = "水是干净的" if water < FISH_DIRTY_DAYS else f"水{'有点' if water < FISH_FOUL_DAYS else '很'}浑（{water}天没换）"
        return (f"窗台上的鱼缸里养着一条{FISH_KIND}，" + (f"叫{t['name']}" if t.get("name") else "还没起名字")
                + f"，这会儿{doing_at(t, at)}（{eaten}；{clean}）")

    @staticmethod
    def tank_matters(room: Room, now: datetime) -> bool:
        """Worth a place among the few room lines of a chat turn: it just came, wants feeding
        or clean water, or has gone listless."""
        t = room.tank
        if not t:
            return False
        today = now.date()
        return (_days(t["since"], today) <= 1 or t.get("sad") or _days(t["water"], today) >= FISH_DIRTY_DAYS
                or (_days(t["fed"], today) >= 1 and now.hour >= 10))

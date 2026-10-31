"""Her cottage (decision 26): the room itself, how time moves it, and what she sees of it.

The room is reality; her head is memory. It changes three ways: him (visitor.py), the rules of
what she does (actions.py, shop.py), and time (`advance`: she sleeps, eats at mealtimes, food
goes off, what she started finishes). Her drawer is drawer.py; what everything is made of is
state.py; her windowsill pots are garden.py, her goldfish tank.py. The file is data/cottage/now.json, plain enough for him to read and edit. No model calls.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import asdict, fields
from datetime import datetime, time, timedelta
from pathlib import Path

from fish.config import owner_words
from fish.cottage.actions import ActionsMixin
from fish.cottage.drawer import DrawerMixin
from fish.cottage.garden import GardenMixin
from fish.cottage.guest import GuestMixin
from fish.cottage.rules import (ACTIONS, ATE_RECENTLY_HOURS, ENERGY_PER_HOUR, HUNGER_PER_HOUR, HUNGRY, SLEEP_FROM,
                                WAKE_AT, asleep_hours, mealtime)
from fish.cottage.shop import ShopMixin
from fish.cottage.tank import TankMixin
from fish.cottage.state import (BED_WORDS, COUNT_WORDS, KEEP_EVENTS, KEEP_MEALS, Change, Offer, Room, _days_left,
                                _iso, can_cook, fresh, invented_act, put_in, rice_word)
from fish.cottage.visitor import VisitorMixin

TODAY_SHOWN = 6  # what happened at home today, shown in a chat turn (two lines a meal since decision 32)

__all__ = ["Change", "Cottage", "Offer", "Room", "invented_act"]


def _wake_between(last: datetime, now: datetime) -> bool:
    wake = datetime.combine(now.date(), WAKE_AT)
    if wake > now:
        wake -= timedelta(days=1)
    return last < wake


def _awake_hours(last: datetime, now: datetime) -> float:
    """Hours she was up between two moments, to the second: the night's sleep (SLEEP_FROM to
    WAKE_AT) does not count. Counting in whole quarter hours made every poll (half a minute
    apart) a quarter hour awake: 10-28 she was starving and spent an hour after a meal."""
    t, awake = max(last, now - timedelta(hours=48)), 0.0
    while t < now:
        end = min(now, datetime.combine(t.date() + timedelta(days=1), time(0)))
        night = (datetime.combine(t.date(), SLEEP_FROM), datetime.combine(t.date(), WAKE_AT))
        asleep = max(0.0, (min(end, night[1]) - max(t, night[0])).total_seconds())
        awake += (end - t).total_seconds() - asleep
        t = end
    return awake / 3600


class Cottage(ActionsMixin, ShopMixin, VisitorMixin, DrawerMixin, GuestMixin, GardenMixin, TankMixin):
    put_in = staticmethod(put_in)  # into the fridge (state.py), kept here for old callers

    def __init__(self, path: Path) -> None:
        self.path = path

    # --- the file ------------------------------------------------------------

    def load(self, now: datetime | None = None) -> Room:
        """The room as the file says. A file he broke while editing raises ValueError."""
        if not self.path.exists():
            room = fresh(now or datetime.now())
            self.save(room)
            return room
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"{self.path} 不是合法的 JSON：{e}") from e
        known = {f.name for f in fields(Room)}
        return Room(**{k: v for k, v in data.items() if k in known})

    def save(self, room: Room) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(room), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)  # the service and `fish cottage` never see half a file

    @staticmethod
    def note(room: Room, now: datetime, line: str, change: Change | None = None, *, routine: bool = False) -> None:
        """routine: a meal eaten on time, the day going as days go; not news worth telling."""
        room.events.append({"ts": _iso(now), "line": line} | ({"routine": True} if routine else {}))
        if change is not None:
            change.lines.append(line)

    # --- time ----------------------------------------------------------------

    def advance(self, now: datetime | None = None) -> Change:
        """Bring the room up to now: an action runs its course, she sleeps and wakes, food goes
        off, a mealtime comes and she eats what there is. Safe to call as often as you like."""
        now = now or datetime.now()
        room = self.load(now)
        change = Change()
        last = datetime.fromisoformat(room.last) if room.last else now
        if now <= last:
            return change
        awake = _awake_hours(last, now)
        self._shop_on_the_way(room, now)  # done choosing: the bag is packed
        change.hunger += HUNGER_PER_HOUR * awake
        change.energy -= ENERGY_PER_HOUR * awake

        if room.until and datetime.fromisoformat(room.until) <= now:
            done = datetime.fromisoformat(room.until)
            if room.doing == ACTIONS["nap"].doing:
                room.bed = "乱"
                change.slept.append((done - timedelta(minutes=ACTIONS["nap"].minutes), done))
            if room.pending.get("buy") is not None:  # home from the shop: what she bought is in now (decision 35)
                self._shop_home(room, done, change)
            else:  # a meal is eaten, the washing up is done (actions.py)
                self._finish(room, done, change)
            room.doing, room.until = "", ""
        if asleep_hours(now):
            if not room.doing:
                room.doing, room.bed = "睡觉", "在睡"
        elif room.doing == "睡觉" or _wake_between(last, now):
            if room.doing == "睡觉":
                room.doing = ""
            room.bed = "乱"  # up for the day; the bed stays as she left it until she makes it
            woke = datetime.combine(now.date() if now.time() >= WAKE_AT else now.date() - timedelta(days=1), WAKE_AT)
            change.slept.append((datetime.combine(woke.date(), SLEEP_FROM), woke))

        self._guest_step(room, now, change)  # he comes at the hour he said, goes at the hour he leaves
        self._garden_step(room, now, change)  # each morning her pots grow a day, or wilt (garden.py)
        self._tank_step(room, now, change)  # her goldfish turns listless, or comes round, and does its little things (tank.py)

        for item in list(room.fridge):
            if _days_left(item, now.date()) <= 0:
                room.fridge.remove(item)
                self.note(room, now, f"{item['name']}放坏了，扔了", change)

        meal = mealtime(now)
        key = f"{now.date().isoformat()} {meal}"
        if meal and key not in room.meals and not room.doing and not self.waiting_for_him(room, now):
            room.meals.append(key)
            if room.ate and now - datetime.fromisoformat(room.ate) < timedelta(hours=ATE_RECENTLY_HOURS):
                pass  # she cooked a little while ago; that was this meal
            elif can_cook(room):
                change += self._apply(room, "cook", now, meal=meal, routine=True)
            elif room.rice > 0:
                change += self._apply(room, "rice", now, meal=meal, routine=True)
            else:
                self.note(room, now, f"到{meal}的点了，家里没东西吃，饿着", change)

        room.events = [e for e in room.events if now - datetime.fromisoformat(e["ts"]) < KEEP_EVENTS]
        room.meals = room.meals[-KEEP_MEALS:]
        room.last = now.isoformat(timespec="seconds")  # to the second: polls are half a minute apart
        self.save(room)
        return change

    # --- what she sees -------------------------------------------------------

    @staticmethod
    def lines(room: Room) -> dict[str, str]:
        meals = Counter()
        for i in room.fridge:  # eggs bought on two days are still just eggs to her
            meals[i["name"]] += i["meals"]
        food = "冰箱里有" + "、".join(f"{n}（够 {k} 顿）" for n, k in meals.items()) if meals else "冰箱空了"
        sink = "、".join(n if k == 1 else f"{COUNT_WORDS.get(k, k)}个{n}" for n, k in Counter(room.sink).items())
        out = {
            "food": f"{food}；米缸{rice_word(room.rice)}",
            "sink": f"水槽里有{sink}没洗" if room.sink else "水槽是干净的",
            "bed": BED_WORDS.get(room.bed, room.bed),
            "sill": "窗台上：" + "、".join(room.sill) if room.sill else "窗台空着",
            "pots": GardenMixin.pots_line(room),
        }
        if room.guest:  # him, here or coming (decision 41)
            out["guest"] = GuestMixin.guest_line(room)
        if room.tank:  # the goldfish he gave her (decision 43)
            out["tank"] = TankMixin.tank_line(room)
        return out

    @staticmethod
    def doing_line(room: Room, *, chatting: bool = False, now: datetime | None = None) -> str:
        if not room.doing:
            return ""
        if room.doing == "睡觉":
            return owner_words("你在睡觉，被他的消息吵醒了") if chatting else "你在睡觉"
        if room.doing == ACTIONS["shop"].doing:
            return ShopMixin.trip_line(room, now)
        return f"你这会儿在{room.doing}，大概到 {room.until[11:16]}"

    @staticmethod
    def today(room: Room, now: datetime) -> list[str]:
        day = now.date().isoformat()
        return [f"{e['ts'][11:16]} {e['line']}" for e in room.events if e["ts"].startswith(day)]

    def for_chat(self, now: datetime, hunger: float) -> str:
        """A few lines for a chat turn: what she is doing, at most three things in the room
        that matter now, and what happened at home today."""
        room = self.load(now)
        all_lines = self.lines(room)
        wanted = ["guest"] if room.guest else []
        if hunger >= HUNGRY or mealtime(now) or not room.fridge or room.rice < 4:
            wanted.append("food")
        if len(room.sink) >= 2:
            wanted.append("sink")
        if room.bed == "乱" and (now.hour < 12 or now.hour >= 21):
            wanted.append("bed")
        if self.pots_matter(room, now):
            wanted.append("pots")
        if self.tank_matters(room, now):
            wanted.append("tank")
        if room.sill:
            wanted.append("sill")
        wanted.append("food")
        picked = list(dict.fromkeys(wanted))[:3]
        out = [x for x in (self.doing_line(room, chatting=True, now=now),) if x]
        out.append("屋里：" + "；".join(all_lines[k] for k in picked) + "。")
        done = self.today(room, now)[-TODAY_SHOWN:]
        # said even when nothing happened: otherwise she goes by what she said in the chat (10-29:
        # "买了米和鸡蛋" while the room never left, then "我去把米缸填上" with no rice to pour)
        out.append("你今天在家：" + "；".join(done) + "。" if done else "你今天在家还什么都没做。")
        return "\n".join(out)

    def menu_for_chat(self, now: datetime, hunger: float, energy: float) -> str:
        """What she could start right now, by key, for a chat turn (decision 35). "" when she is
        busy with something, so a trip to the shop is not started twice."""
        offers = self.offers(now, hunger, energy)
        if not offers:
            return ""
        return "你现在能做的（说要去做就在 do 里填前面的英文）：" + "；".join(
            f"{o.key} {o.line}" + (f"（{o.arg_hint}，写在 do_arg）" if o.arg_hint else "") for o in offers) + "。"

    def for_leisure(self, now: datetime) -> str:
        """Everything in the room, for the moment she decides what to do."""
        room = self.load(now)
        out = list(self.lines(room).values())
        done = self.today(room, now)
        if done:
            out.append("你今天在家：" + "；".join(done))
        return "\n".join(f"- {x}" for x in out)

    def between(self, start: datetime, end: datetime, *, routine: bool = True) -> list[str]:
        """What happened at home in a stretch of time, for her diary; routine=False leaves out
        the meals eaten on time."""
        room = self.load(end)
        return [f"{e['ts'][11:16]} {e['line']}" for e in room.events
                if start <= datetime.fromisoformat(e["ts"]) < end and (routine or not e.get("routine"))]

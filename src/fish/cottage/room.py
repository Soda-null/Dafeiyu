"""What is in her cottage right now (decision 26) and the three ways it changes.

The room is reality; her head is memory. Him: by hand in the file or with `fish cottage`.
The rules: an action she picked from her free-time menu. Time: she sleeps, eats at
mealtimes, food goes off. What she says changes nothing here. The file is
data/cottage/now.json, plain enough for him to read and edit. No model calls.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime, time, timedelta
from pathlib import Path

from fish.config import owner_words
from fish.cottage.rules import (ACTIONS, ATE_RECENTLY_HOURS, CARRY, ENERGY_PER_HOUR, FRIDGE_SLOTS, GOODS, HUNGER_PER_HOUR,
                                HUNGRY, RICE, RICE_FULL, SHOP_WALK_MINUTES, SINK_LIMIT, SLEEP_FROM, TIRED, WAKE_AT, Good,
                                asleep_hours, in_stock, mealtime, shop_open)

KEEP_EVENTS = timedelta(days=2)
# What she may not write about herself once she has a room: things done to it. Doing, buying
# and eating happen through the rules and are in `events`; her own notes keep thoughts and
# plans. Wanting to ("想做饭", "打算去买") is a thought and passes.
INVENTED_ACT = re.compile(r"(?<![想要打算准备])(做|煮|炒|烧|吃|买|洗|叠|收拾|打扫|种|养|睡|躺|煎|炖|蒸)(了|过|完|着|好)")
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
    sill: list[str] = field(default_factory=list)  # what he put on the windowsill
    meals: list[str] = field(default_factory=list)  # "2026-10-28 午饭": that mealtime is done with
    ate: str = ""  # when she last ate
    pending: dict = field(default_factory=dict)  # a meal on the stove: {"hunger", "line", "routine"} at `until`
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


def _good(name: str) -> Good:
    return GOODS.get(name, Good(name, 1, None))  # something he put in that the shop does not sell


def _days_left(item: dict, today: date) -> float:
    good = _good(item["name"])
    if good.keeps_days is None:
        return float("inf")
    return good.keeps_days - (today - date.fromisoformat(item["bought"])).days


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


class Cottage:
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
        change.hunger += HUNGER_PER_HOUR * awake
        change.energy -= ENERGY_PER_HOUR * awake

        if room.until and datetime.fromisoformat(room.until) <= now:
            done = datetime.fromisoformat(room.until)
            if room.doing == ACTIONS["nap"].doing:
                room.bed = "乱"
                change.slept.append((done - timedelta(minutes=ACTIONS["nap"].minutes), done))
            if room.pending:  # the meal is ready: she eats now, not when she started cooking
                self.note(room, done, room.pending["line"], change, routine=room.pending.get("routine", False))
                change.hunger += room.pending["hunger"]
                change.ate.append((done, room.pending["hunger"]))
                room.ate, room.pending = _iso(done), {}
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

        for item in list(room.fridge):
            if _days_left(item, now.date()) <= 0:
                room.fridge.remove(item)
                self.note(room, now, f"{item['name']}放坏了，扔了", change)

        meal = mealtime(now)
        key = f"{now.date().isoformat()} {meal}"
        if meal and key not in room.meals and not room.doing:
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

    # --- what she can do -----------------------------------------------------

    def offers(self, now: datetime, hunger: float, energy: float) -> list[Offer]:
        """The actions she could take right now, only the ones that would work."""
        room = self.load(now)
        if room.doing:
            return []
        out = []
        if hunger >= HUNGRY and can_cook(room):
            out.append(Offer("cook", f"做顿饭（冰箱里有{'、'.join(i['name'] for i in room.fridge)}）"))
        if hunger >= HUNGRY and room.rice > 0:
            out.append(Offer("rice", "煮锅白饭"))
        if room.sink:
            out.append(Offer("wash", f"洗碗（水槽里有{'、'.join(room.sink)}）"))
        if room.bed == "乱":
            out.append(Offer("bed", "叠被子"))
        if energy < TIRED:
            out.append(Offer("nap", "睡个午觉"))
        if shop_open(now) and shop_open(now + timedelta(minutes=SHOP_WALK_MINUTES)):
            out.append(Offer("shop", f"去镇上的菜店买菜（今天有：{'、'.join(in_stock(now))}）",
                             f"想买的，用顿号隔开，最多 {CARRY} 样"))
        return out

    def act(self, key: str, now: datetime, arg: str = "") -> Change | None:
        """Do what she picked. None when the room no longer allows it (nothing changes)."""
        room = self.load(now)
        if not self._possible(room, key, now):
            return None
        change = self._apply(room, key, now, arg=arg)
        self.save(room)
        return change

    @staticmethod
    def _possible(room: Room, key: str, now: datetime) -> bool:
        if room.doing or key not in ACTIONS:
            return False
        return {"cook": can_cook(room), "rice": room.rice > 0, "wash": bool(room.sink),
                "bed": room.bed == "乱", "nap": True, "shop": shop_open(now)}[key]

    def _apply(self, room: Room, key: str, now: datetime, *, arg: str = "", meal: str | None = None,
               routine: bool = False) -> Change:
        action = ACTIONS[key]
        change = Change(hunger=action.hunger, energy=action.energy)
        if key in ("rice", "cook"):
            # Two steps (decision 32): now she starts; when `until` comes the meal is ready and
            # she eats (advance). Until then she is not fed, and has not eaten.
            change.hunger = 0.0
            room.rice -= 1
            if key == "rice":
                room.sink.append("电饭煲内胆")
                line = f"开始煮{meal}的白饭" if meal else "开始煮一锅白饭"
                done = f"{meal}的白饭煮好了，吃了" if meal else "白饭煮好了，吃了"
            else:
                used = self._take_for_meal(room, now.date())
                room.sink.append("锅")
                line = f"开始做{meal or '饭'}，用{'、'.join(used)}"
                done = f"{meal}做好了，吃了" if meal else "饭做好了，吃了"
            room.pending = {"hunger": action.hunger, "line": done, "routine": routine}
        elif key == "wash":
            room.sink.clear()
            line = "洗了碗"
        elif key == "bed":
            room.bed = "叠好"
            line = "叠了被子"
        elif key == "nap":
            room.bed = "在睡"
            line = "睡了个午觉"
        else:
            line = self._buy(room, arg, now)
        room.doing, room.until = action.doing, _iso(now + timedelta(minutes=action.minutes))
        self.note(room, now, line, change, routine=routine)
        return change

    @staticmethod
    def _take_for_meal(room: Room, today: date) -> list[str]:
        """One meal from what goes off first, at most two kinds."""
        used = []
        for item in sorted(room.fridge, key=lambda i: _days_left(i, today))[:2]:
            item["meals"] -= 1
            used.append(item["name"])
            if item["meals"] <= 0:
                room.fridge.remove(item)
        return used

    def _buy(self, room: Room, arg: str, now: datetime) -> str:
        stock = in_stock(now)
        wanted = [w for w in (x.strip() for x in SPLIT.split(arg)) if w]
        bought, missing, no_room = [], [], []
        for w in wanted:
            name = next((s for s in stock if s in w or w in s), None)
            if name is None:
                missing.append(w)
            elif name in bought:
                continue
            elif len(bought) >= CARRY:
                break
            elif name == RICE:
                room.rice = RICE_FULL
                bought.append(name)
            elif not self.put_in(room, name, now, None):
                no_room.append(name)
            else:
                bought.append(name)
        line = f"去菜店买了{'、'.join(bought)}" if bought else "去菜店转了一圈，什么也没买"
        if missing:
            line += f"（想要的{'、'.join(missing)}没有）"
        if no_room:
            line += f"（{'、'.join(no_room)}冰箱放不下了）"
        return line

    @staticmethod
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

    # --- him -----------------------------------------------------------------

    def give(self, what: str, now: datetime, meals: int | None = None) -> str:
        """He puts food in (rice into the jar, the rest into the fridge). Returns what happened."""
        room = self.load(now)
        if what == RICE:
            room.rice = RICE_FULL
            line = owner_words("他把米缸装满了")
        elif self.put_in(room, what, now, meals):
            line = owner_words(f"他往冰箱里放了{what}")
        else:
            return "冰箱满了，没放进去"
        self.note(room, now, line)
        self.save(room)
        return line

    def put_on_sill(self, what: str, now: datetime) -> str:
        room = self.load(now)
        room.sill.append(owner_words(f"{what}（他 {now.month}-{now.day} 送的）"))
        line = owner_words(f"他在窗台上放了{what}")
        self.note(room, now, line)
        self.save(room)
        return line

    # --- what she sees -------------------------------------------------------

    @staticmethod
    def lines(room: Room) -> dict[str, str]:
        meals = Counter()
        for i in room.fridge:  # eggs bought on two days are still just eggs to her
            meals[i["name"]] += i["meals"]
        food = "冰箱里有" + "、".join(f"{n}（够 {k} 顿）" for n, k in meals.items()) if meals else "冰箱空了"
        sink = "、".join(n if k == 1 else f"{COUNT_WORDS.get(k, k)}个{n}" for n, k in Counter(room.sink).items())
        return {
            "food": f"{food}；米缸{rice_word(room.rice)}",
            "sink": f"水槽里有{sink}没洗" if room.sink else "水槽是干净的",
            "bed": BED_WORDS.get(room.bed, room.bed),
            "sill": "窗台上：" + "、".join(room.sill) if room.sill else "窗台空着",
        }

    @staticmethod
    def doing_line(room: Room, *, chatting: bool = False) -> str:
        if not room.doing:
            return ""
        if room.doing == "睡觉":
            return owner_words("你在睡觉，被他的消息吵醒了") if chatting else "你在睡觉"
        until = room.until[11:16]
        if room.doing == ACTIONS["shop"].doing:
            return f"你出门去菜店了，大概 {until} 到家"
        return f"你这会儿在{room.doing}，大概到 {until}"

    @staticmethod
    def today(room: Room, now: datetime) -> list[str]:
        day = now.date().isoformat()
        return [f"{e['ts'][11:16]} {e['line']}" for e in room.events if e["ts"].startswith(day)]

    def for_chat(self, now: datetime, hunger: float) -> str:
        """A few lines for a chat turn: what she is doing, at most three things in the room
        that matter now, and what happened at home today."""
        room = self.load(now)
        all_lines = self.lines(room)
        wanted = []
        if hunger >= HUNGRY or mealtime(now) or not room.fridge or room.rice < 4:
            wanted.append("food")
        if len(room.sink) >= 2:
            wanted.append("sink")
        if room.bed == "乱" and (now.hour < 12 or now.hour >= 21):
            wanted.append("bed")
        if room.sill:
            wanted.append("sill")
        wanted.append("food")
        picked = list(dict.fromkeys(wanted))[:3]
        out = [x for x in (self.doing_line(room, chatting=True),) if x]
        out.append("屋里：" + "；".join(all_lines[k] for k in picked) + "。")
        done = self.today(room, now)[-3:]
        if done:
            out.append("你今天在家：" + "；".join(done) + "。")
        return "\n".join(out)

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

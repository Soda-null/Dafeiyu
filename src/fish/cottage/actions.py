"""What she can do in her room (decisions 26, 32, 35, 36): cook, boil rice, wash up, make the
bed, nap, leave him something on the windowsill; the shop is shop.py. Only what would work is
offered; the rules decide what it changes. Meals and washing take their time: they are started
here and finished when `until` comes (`_finish`, called by the room's time step)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from fish.cottage.rules import ACTIONS, CARRY, HUNGRY, NOTE_PREFIX, SHOP_WALK_MINUTES, TIRED, in_stock, shop_open
from fish.cottage.state import SPLIT, Change, Offer, Room, _days_left, _iso, can_cook

LEAVE_AT_ONCE = 3


def _leaving(room: Room, arg: str) -> list[str]:
    """What she can leave him for `arg`: a note ("纸条：……") as written, or the fridge items it
    names, up to LEAVE_AT_ONCE ("牛奶、鸡蛋": both, 10-29 checkup: she said two and left one).
    Empty when neither: she cannot leave what she does not have."""
    arg = arg.strip()
    if arg.startswith(NOTE_PREFIX):
        words = arg[len(NOTE_PREFIX):].lstrip("：: ").strip()
        return [f"{NOTE_PREFIX}：{words}"] if words else []
    names: list[str] = []
    for want in (w.strip() for w in SPLIT.split(arg)):
        name = next((i["name"] for i in room.fridge if want and (i["name"] in want or want in i["name"])), None)
        if name and name not in names:
            names.append(name)
    return names[:LEAVE_AT_ONCE]


class ActionsMixin:
    """Part of Cottage (room.py): her actions. Uses the room's load / save / note."""

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
        out.append(Offer("leave", "在窗台上给他留点东西（冰箱里有的，或者写张纸条）",
                         f"留什么：冰箱里的一样，或者\"{NOTE_PREFIX}：想写的话\""))
        if shop_open(now) and shop_open(now + timedelta(minutes=SHOP_WALK_MINUTES)) and not self.just_shopped(room, now):
            out.append(Offer("shop", f"去镇上的菜店买菜、买米（米缸和冰箱只能这样补；今天有：{'、'.join(in_stock(now))}）",
                             f"想买的，用顿号隔开，最多 {CARRY} 样"))
        return out

    def act(self, key: str, now: datetime, arg: str = "") -> Change | None:
        """Do what she picked. None when the room no longer allows it (nothing changes)."""
        room = self.load(now)
        if not self._possible(room, key, now) or (key == "leave" and not _leaving(room, arg)):
            return None
        change = self._apply(room, key, now, arg=arg)
        self.save(room)
        return change

    def _possible(self, room: Room, key: str, now: datetime) -> bool:
        if room.doing or key not in ACTIONS:
            return False
        return {"cook": can_cook(room), "rice": room.rice > 0, "wash": bool(room.sink),
                "bed": room.bed == "乱", "nap": True, "shop": shop_open(now) and not self.just_shopped(room, now),
                "leave": True}[key]

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
                # what was in it, said again when it is eaten: the start may be out of sight by then
                # (10-29 checkup: asked what lunch was, she guessed "煎蛋" over 青菜豆腐)
                done = (f"{meal}做好了，吃了（{'、'.join(used)}）" if meal else f"饭做好了，吃了（{'、'.join(used)}）")
            room.pending = {"hunger": action.hunger, "line": done, "routine": routine}
        elif key == "wash":
            line = "开始洗碗"
            room.pending = {"wash": True, "routine": routine}  # the sink is clean when she is done
        elif key == "bed":
            room.bed = "叠好"
            line = "叠了被子"
        elif key == "nap":
            room.bed = "在睡"
            line = "睡了个午觉"
        elif key == "leave":
            names = _leaving(room, arg)
            if names[0].startswith(NOTE_PREFIX):
                room.sill.append(f"一张{names[0]}（给他留的，{now.month}-{now.day}）")
                line = f"在窗台上给他留了一张{names[0]}"
            else:
                for what in names:
                    item = next(i for i in room.fridge if i["name"] == what)
                    item["meals"] -= 1
                    if item["meals"] <= 0:
                        room.fridge.remove(item)
                    room.sill.append(f"{what}（给他留的，{now.month}-{now.day}）")
                line = f"在窗台上给他留了{'、'.join(names)}"
        else:
            line = self._start_shop(room, arg, routine)
        room.doing, room.until = action.doing, _iso(now + timedelta(minutes=action.minutes))
        self.note(room, now, line, change, routine=routine)
        return change

    def _finish(self, room: Room, done: datetime, change: Change) -> None:
        """`until` came for a meal or the washing up: the meal is eaten now, not when she started
        cooking; the sink is clean now, not when she started washing."""
        if room.pending.get("wash"):
            room.sink.clear()
            self.note(room, done, "洗完了碗", change, routine=room.pending.get("routine", False))
            room.pending = {}
        elif room.pending:
            self.note(room, done, room.pending["line"], change, routine=room.pending.get("routine", False))
            change.hunger += room.pending["hunger"]
            change.ate.append((done, room.pending["hunger"]))
            room.ate, room.pending = _iso(done), {}

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

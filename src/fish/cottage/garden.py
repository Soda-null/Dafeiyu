"""Her windowsill pots (decision 42): something of hers that goes on from day to day. She sows,
waters and picks; time grows it, a morning at a time. A pot left dry wilts and stops growing,
and left longer it dies. What she picks goes into the fridge, so she can cook it or leave it on
the sill for him. Like the rest of the room, only the rules and time move it: saying "冒芽了"
makes nothing sprout."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from fish.cottage.rules import DIE_DAYS, FRIDGE_SLOTS, PLANTS, RIPE_AT_MOST, WAKE_AT, WILT_DAYS, Plant
from fish.cottage.state import COUNT_WORDS, Change, Offer, Room, put_in

KEYS = ("sow", "water", "pick")


def plant_named(arg: str) -> Plant | None:
    """"种点葱吧" -> 小葱; None when it names nothing she has seeds of."""
    return next((p for p in PLANTS.values() if any(w in arg for w in (p.name, *p.also))), None)


def _dry(pot: dict, today: date) -> int:
    return (today - date.fromisoformat(pot["watered"])).days


def _count(n: int) -> str:
    return COUNT_WORDS.get(n, str(n))


def _fits(room: Room, name: str) -> bool:
    kinds = {i["name"] for i in room.fridge}
    return name in kinds or len(kinds) < FRIDGE_SLOTS


def _today(room: Room) -> date:
    return date.fromisoformat(room.last[:10]) if room.last else date.today()


class GardenMixin:
    """Part of Cottage (room.py): her pots. Uses the room's note; actions.py asks it what she
    could do with them, and room.py lets time grow them."""

    @staticmethod
    def garden_offers(room: Room, now: datetime) -> list[Offer]:
        planted = [p for p in room.pots if p]
        out = []
        thirsty = [p["plant"] for p in planted if _dry(p, now.date()) >= 1]
        thirsty += [f["name"] for f in room.flowers if _dry(f, now.date()) >= 1]  # her flowers (florist.py)
        if thirsty:
            names = [p["plant"] for p in planted] + [f["name"] for f in room.flowers]
            out.append(Offer("water", "给窗台上的" + "、".join(names) + "浇水"))
        ready = [p["plant"] for p in planted if p.get("ready") and _fits(room, p["plant"])]
        if ready:
            out.append(Offer("pick", "摘" + "、".join(ready) + "（摘下来放冰箱）"))
        if len(planted) < len(room.pots):
            seeds = "、".join(PLANTS)
            out.append(Offer("sow", f"在窗台的空花盆里种点东西（柜子里有{seeds}的种子）", f"种哪样：{seeds}"))
        return out

    def garden_possible(self, room: Room, key: str, now: datetime, arg: str) -> bool:
        return any(o.key == key for o in self.garden_offers(room, now)) and (key != "sow" or plant_named(arg) is not None)

    def _garden_apply(self, room: Room, key: str, now: datetime, arg: str) -> str:
        today = now.date().isoformat()
        if key == "sow":
            plant = plant_named(arg)
            i = next(i for i, p in enumerate(room.pots) if not p)
            room.pots[i] = {"plant": plant.name, "sown": today, "watered": today, "days": 0, "ready": 0}
            return f"在窗台的花盆里种下了{plant.name}，浇了水"
        if key == "water":
            planted = [p for p in room.pots if p]
            for p in planted + room.flowers:
                p["watered"] = today
            return "给" + "、".join([p["plant"] for p in planted] + [f["name"] for f in room.flowers]) + "浇了水"
        picked = []
        for i, p in enumerate(room.pots):
            plant = PLANTS[p["plant"]] if p else None
            if not p or not p.get("ready") or not _fits(room, plant.name):
                continue
            n = p["ready"]
            put_in(room, plant.name, now, plant.meals * n)
            if plant.again is None:
                room.pots[i] = {}
                picked.append(f"{plant.name}（花盆空出来了）")
                continue
            p["ready"] = 0
            if plant.cut:
                p["next"] = p["days"] + plant.again
                picked.append(f"一把{plant.name}")
            else:
                picked.append(f"{_count(n)}颗{plant.name}")
        verb = "剪了" if all(x.startswith("一把") for x in picked) else "摘了"
        return verb + "、".join(picked) + "，放进冰箱"

    def _garden_step(self, room: Room, now: datetime, change: Change) -> None:
        """Every morning she is up, each pot grows a day, or wilts, or dies. A room from before
        the pots counts from the last time time moved it (`last` is not yet moved on to now)."""
        if not room.grew:
            room.grew = (room.last or now.isoformat())[:10]
        day = date.fromisoformat(room.grew) + timedelta(days=1)
        while day <= now.date() and datetime.combine(day, WAKE_AT) <= now:
            at = datetime.combine(day, WAKE_AT)
            for i, p in enumerate(room.pots):
                if p:
                    self._grow(room, i, day, at, change)
            room.grew = day.isoformat()
            day += timedelta(days=1)

    def _grow(self, room: Room, i: int, day: date, at: datetime, change: Change) -> None:
        p = room.pots[i]
        plant = PLANTS[p["plant"]]
        dry = _dry(p, day)
        if dry >= DIE_DAYS:
            room.pots[i] = {}
            self.note(room, at, f"{plant.name}{_count(dry)}天没浇水，干死了，只好拔了", change)
            return
        if dry >= WILT_DAYS:
            if not p.get("wilted"):
                p["wilted"] = True
                self.note(room, at, f"{plant.name}{_count(dry)}天没浇水，蔫了，叶子耷拉着", change)
            return
        if p.pop("wilted", False):  # watered again: it comes round, and grows from tomorrow
            self.note(room, at, f"{plant.name}缓过来了", change)
            return
        p["days"] += 1
        words = next((w for d, w in plant.stages if d == p["days"]), "")
        if p["days"] == plant.ripe_at:
            p["ready"], p["next"], words = 1, plant.ripe_at + (plant.again or 0), plant.ready_words
        elif p.get("next") and p["days"] >= p["next"]:  # the next picking, once the first has come
            p["next"] = p["days"] + plant.again
            most = 1 if plant.cut else RIPE_AT_MOST
            if p["ready"] < most:
                p["ready"] += 1
                words = plant.again_words
        if words:
            self.note(room, at, plant.name + words, change)

    @staticmethod
    def pots_line(room: Room) -> str:
        today = _today(room)
        planted = [p for p in room.pots if p]
        if not planted:
            return "窗台上的花盆都空着"
        parts = []
        for p in planted:
            plant = PLANTS[p["plant"]]
            # how long until it can be eaten: told only "还没出芽" / "还不能摘", asked "有葱吗" she said
            # "有", and "我炒个葱蛋" the day after the onions came up (10-30 trials)
            grown = next((w for d, w in reversed(plant.stages) if p["days"] >= d), "还没出芽")
            grown += f"，还要长 {plant.ripe_at - p['days']} 天才能{'剪' if plant.cut else '摘'}，现在没得吃"
            if p.get("wilted"):
                grown = "蔫了"
            elif p.get("ready"):
                grown = plant.ready_words if p["ready"] == 1 or plant.cut else f"红了{_count(p['ready'])}颗，能摘了"
            dry = _dry(p, today)
            water = "今天浇过水" if dry == 0 else "昨天浇的水" if dry == 1 else f"{_count(dry)}天没浇水了"
            sown = (today - date.fromisoformat(p["sown"])).days + 1
            parts.append(f"{p['plant']}（种下第 {sown} 天，{grown}，{water}）")
        empty = len(room.pots) - len(planted)
        return "窗台上的花盆：" + "、".join(parts) + (f"；还空着{_count(empty) if empty > 1 else '一'}个" if empty else "")

    @staticmethod
    def pots_matter(room: Room, now: datetime) -> bool:
        """Worth a place among the few room lines of a chat turn: something to pick, a pot
        drooping or going dry."""
        return any(p and (p.get("ready") or p.get("wilted") or _dry(p, now.date()) >= 2) for p in room.pots)

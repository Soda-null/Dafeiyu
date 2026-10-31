"""The flower shop in town and her flowers on the windowsill (decision 45). Fifteen minutes'
walk, closed on Mondays; it sells small potted plants, a couple that are always there and what
is in season. What she buys goes on the sill only when she is home. A flower does not grow:
watered (garden.py waters it with her pots) it keeps; left dry it droops, then dies."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from fish.cottage.rules import (ACTIONS, FLORIST_AGAIN_HOURS, FLORIST_WALK_MINUTES, FLOWER_SPOTS, FLOWERS,
                                Flower, asleep_hours, florist_open, flowers_in_stock)
from fish.cottage.state import COUNT_WORDS, SPLIT, Change, Offer, Room

KEYS = ("florist",)
FLORIST = ACTIONS["florist"]
BACK = "从花店回来了"


def flower_named(word: str, stock: list[str]) -> str | None:
    """"菊花" -> 小菊花, when the shop has it."""
    return next((n for n in stock if n in word or word in n or any(w in word for w in FLOWERS[n].also)), None)


def _dry(f: dict, today: date) -> int:
    return (today - date.fromisoformat(f["watered"])).days


def _count(n: int) -> str:
    return COUNT_WORDS.get(n, str(n))


def _flower(f: dict) -> Flower:
    return FLOWERS.get(f["name"], Flower(f["name"], (), 3))


class FloristMixin:
    """Part of Cottage (room.py): the flower shop trip and her flowers. Uses the room's note."""

    @staticmethod
    def just_at_florist(room: Room, now: datetime) -> bool:
        return any(e["line"].startswith(BACK) and now - datetime.fromisoformat(e["ts"]) < timedelta(hours=FLORIST_AGAIN_HOURS)
                   for e in room.events)

    def florist_offers(self, room: Room, now: datetime) -> list[Offer]:
        there = now + timedelta(minutes=FLORIST_WALK_MINUTES)
        if not (florist_open(now) and florist_open(there)) or self.just_at_florist(room, now):
            return []
        room_for = FLOWER_SPOTS - len(room.flowers)
        if room_for <= 0:
            return []
        stock = "、".join(flowers_in_stock(there))
        return [Offer("florist", f"去镇上的花店买盆花摆窗台（走 {FLORIST_WALK_MINUTES} 分钟；今天有：{stock}）",
                      f"想买哪样，用顿号隔开，最多 {room_for} 盆")]

    def florist_possible(self, room: Room, key: str, now: datetime, arg: str) -> bool:
        return bool(self.florist_offers(room, now))

    @staticmethod
    def _florist_apply(room: Room, key: str, now: datetime, arg: str) -> str:
        wanted = "、".join(w for w in (x.strip() for x in SPLIT.split(arg)) if w)
        room.pending = {"florist": arg}
        return f"出门去镇上的花店（想买{wanted}）" if wanted else "出门去镇上的花店"

    @staticmethod
    def _flower_bag(room: Room, out_at: datetime) -> tuple[list[str], list[str]]:
        """What she comes away with, and what she wanted and the shop did not have."""
        stock = flowers_in_stock(out_at + timedelta(minutes=FLORIST_WALK_MINUTES))
        bag, missing = [], []
        for w in (x.strip() for x in SPLIT.split(room.pending.get("florist") or "")):
            if not w:
                continue
            name = flower_named(w, stock)
            if name is None:
                missing.append(w)
            elif name not in bag and len(bag) < FLOWER_SPOTS - len(room.flowers):
                bag.append(name)
        return bag, missing

    def _florist_home(self, room: Room, done: datetime, change: Change) -> None:
        """Home from the flower shop: what she bought is on the sill now, watered."""
        bag, missing = self._flower_bag(room, done - timedelta(minutes=FLORIST.minutes))
        today = done.date().isoformat()
        room.flowers += [{"name": n, "bought": today, "watered": today} for n in bag]
        line = f"{BACK}，买了{'、'.join(bag)}，摆在窗台上，浇了水" if bag else f"{BACK}，转了一圈，什么也没买"
        if missing:
            line += f"（想要的{'、'.join(missing)}没有）"
        self.note(room, done, line, change, routine=room.pending.get("routine", False))
        room.been["florist"] = done.isoformat(timespec="minutes")
        room.pending = {}

    @classmethod
    def florist_trip_line(cls, room: Room, now: datetime | None) -> str:
        until = room.until[11:16]
        if now is None or not room.until:
            return f"你出门去花店了，大概 {until} 到家"
        left = (datetime.fromisoformat(room.until) - now).total_seconds() / 60
        if left > FLORIST.minutes - FLORIST_WALK_MINUTES:
            return f"你在去镇上花店的路上，大概 {until} 到家"
        if left > FLORIST_WALK_MINUTES:
            return f"你在花店里挑花，大概 {until} 到家"
        bag, _ = cls._flower_bag(room, datetime.fromisoformat(room.until) - timedelta(minutes=FLORIST.minutes))
        return f"你抱着{'、'.join(bag)}往回走，大概 {until} 到家" if bag else f"你空着手往回走，大概 {until} 到家"

    def _flowers_step(self, room: Room, now: datetime, change: Change) -> None:
        """While she is up: a flower left dry droops (once), dies, or comes round once watered."""
        if asleep_hours(now):
            return
        for f in list(room.flowers):
            dry, wilt = _dry(f, now.date()), _flower(f).wilt_days
            if dry >= 2 * wilt:
                room.flowers.remove(f)
                self.note(room, now, f"窗台上的{f['name']}{_count(dry)}天没浇水，干死了，只好扔了", change)
            elif dry >= wilt and not f.get("wilted"):
                f["wilted"] = True
                self.note(room, now, f"窗台上的{f['name']}{_count(dry)}天没浇水，蔫了", change)
            elif dry < wilt and f.pop("wilted", False):
                self.note(room, now, f"窗台上的{f['name']}浇了水，缓过来了", change)

    @staticmethod
    def flowers_line(room: Room) -> str:
        today = date.fromisoformat(room.last[:10]) if room.last else date.today()
        parts = []
        for f in room.flowers:
            dry = _dry(f, today)
            water = "今天浇过水" if dry == 0 else "昨天浇的水" if dry == 1 else f"{_count(dry)}天没浇水了"
            parts.append(f"{f['name']}（{'蔫了，' if f.get('wilted') else ''}{water}）")
        return "窗台上你自己买的花：" + "、".join(parts)

    @staticmethod
    def flowers_matter(room: Room, now: datetime) -> bool:
        """Worth a place among the room lines of a chat turn: one drooping or about to."""
        return any(f.get("wilted") or _dry(f, now.date()) >= _flower(f).wilt_days - 1 for f in room.flowers)

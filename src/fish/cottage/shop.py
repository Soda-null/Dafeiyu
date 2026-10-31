"""Her trip to the vegetable shop (decision 35): out of the door, ten minutes there, ten in the
shop (what she takes is known as she leaves it), ten back; what she bought is home only when
she is. Just back, she does not go again for a while."""

from __future__ import annotations

from datetime import datetime, timedelta

from fish.cottage.rules import ACTIONS, CARRY, RICE, RICE_FULL, SHOP_AGAIN_HOURS, SHOP_WALK_MINUTES, in_stock
from fish.cottage.state import SPLIT, Change, Room, _iso, put_in

SHOP = ACTIONS["shop"]


class ShopMixin:
    """Part of Cottage (room.py): the shopping trip. Uses the room's note."""

    @staticmethod
    def just_shopped(room: Room, now: datetime) -> bool:
        """Back from the shop less than SHOP_AGAIN_HOURS ago."""
        return any(e["line"].startswith("从菜店回来了") and now - datetime.fromisoformat(e["ts"]) < timedelta(hours=SHOP_AGAIN_HOURS)
                   for e in room.events)

    @staticmethod
    def _start_shop(room: Room, arg: str, routine: bool) -> str:
        """Out of the door now; what she buys is bought at the shop and in the fridge only when
        she is home again, half an hour later."""
        wanted = "、".join(w for w in (x.strip() for x in SPLIT.split(arg)) if w)
        room.pending = {"buy": arg, "routine": routine}
        return f"出门去镇上的菜店（想买{wanted}）" if wanted else "出门去镇上的菜店"

    def _shop_on_the_way(self, room: Room, now: datetime) -> None:
        """A tick during the trip: once she is done choosing, her bag is packed."""
        if room.doing == SHOP.doing and room.pending.get("buy") is not None:
            out_at = datetime.fromisoformat(room.until) - timedelta(minutes=SHOP.minutes)
            if now >= out_at + timedelta(minutes=2 * SHOP_WALK_MINUTES):
                self._pick(room, out_at + timedelta(minutes=2 * SHOP_WALK_MINUTES))

    def _shop_home(self, room: Room, done: datetime, change: Change) -> None:
        """Home from the shop: what she bought is in now."""
        self._pick(room, done - timedelta(minutes=SHOP_WALK_MINUTES))  # if no tick fell in the shop
        line = "从菜店回来了，" + self._unpack(room, done).removeprefix("去菜店")
        self.note(room, done, line, change, routine=room.pending.get("routine", False))
        room.been["shop"] = _iso(done)
        room.pending = {}

    @staticmethod
    def _pick(room: Room, at_shop: datetime) -> None:
        """At the shop, as she leaves it: what she takes from what is sold today (at most CARRY),
        into her bag; nothing is home yet. Once only."""
        p = room.pending
        if p.get("bag") is not None:
            return
        stock = in_stock(at_shop)
        bag, missing = [], []
        for w in (x.strip() for x in SPLIT.split(p.get("buy") or "")):
            if not w:
                continue
            name = next((s for s in stock if s in w or w in s), None)
            if name is None:
                missing.append(w)
            elif name not in bag and len(bag) < CARRY:
                bag.append(name)
        p["bag"], p["missing"], p["at_shop"] = bag, missing, _iso(at_shop)

    @staticmethod
    def _unpack(room: Room, home: datetime) -> str:
        """Home with the bag: rice into the jar, the rest into the fridge while there is room."""
        p = room.pending
        bought, no_room = [], []
        for name in p.get("bag") or []:
            if name == RICE:
                room.rice = RICE_FULL
                bought.append(name)
            elif put_in(room, name, datetime.fromisoformat(p.get("at_shop") or _iso(home)), None):
                bought.append(name)
            else:
                no_room.append(name)
        line = f"去菜店买了{'、'.join(bought)}" if bought else "去菜店转了一圈，什么也没买"
        if p.get("missing"):
            line += f"（想要的{'、'.join(p['missing'])}没有）"
        if no_room:
            line += f"（{'、'.join(no_room)}冰箱放不下了）"
        return line

    @staticmethod
    def trip_line(room: Room, now: datetime | None) -> str:
        """Which part of the trip she is in (10-29 checkup: "刚进门 正在挑")."""
        until = room.until[11:16]
        if now is not None and room.until:
            left = (datetime.fromisoformat(room.until) - now).total_seconds() / 60
            bag = room.pending.get("bag")
            if left > SHOP.minutes - SHOP_WALK_MINUTES:
                return f"你在去镇上菜店的路上，大概 {until} 到家"
            if bag is None:
                return f"你在菜店里挑菜，大概 {until} 到家"
            return (f"你拎着{'、'.join(bag)}往回走，大概 {until} 到家" if bag
                    else f"你空着手往回走（想要的都没有），大概 {until} 到家")
        return f"你出门去菜店了，大概 {until} 到家"

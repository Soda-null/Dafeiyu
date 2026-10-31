"""What he does to her room (decisions 26, 36): puts food in, puts something on her windowsill,
takes something away (what she left him, or a present of his back). `fish cottage` and his
plain words (`fish home`) come through here."""

from __future__ import annotations

from datetime import datetime

from fish.config import owner_words
from fish.cottage.rules import FISH_KIND, RICE, RICE_FULL
from fish.cottage.state import put_in, sill_name


class VisitorMixin:
    """Part of Cottage (room.py): him. Uses the room's load / save / note."""

    def give(self, what: str, now: datetime, meals: int | None = None) -> str:
        """He puts food in (rice into the jar, the rest into the fridge). Returns what happened."""
        room = self.load(now)
        if what == RICE:
            room.rice = RICE_FULL
            line = owner_words("他把米缸装满了")
        elif put_in(room, what, now, meals):
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

    def take(self, what: str, now: datetime, where: str = "") -> str | None:
        """He takes something: off the windowsill (what she left him, or a present of his back)
        or out of the fridge; where "" looks on the sill first. None when there is no such thing."""
        room = self.load(now)
        key = what.strip()
        if not key:
            return None
        line = None
        if where in ("", "sill"):
            item = next((i for i in room.sill if key in sill_name(i) or sill_name(i) in key), None)
            if item is not None and self.tank_holds(room, item):
                return f"鱼缸里养着{FISH_KIND}，缸拿不走"
            if item is not None:
                room.sill.remove(item)
                line = owner_words(f"他从窗台上拿走了{sill_name(item)}")
        if line is None and where in ("", "fridge"):
            item = next((i for i in room.fridge if key in i["name"] or i["name"] in key), None)
            if item is not None:
                room.fridge.remove(item)
                line = owner_words(f"他从冰箱里拿走了{item['name']}")
        if line is None:
            return None
        self.note(room, now, line)
        self.save(room)
        return line

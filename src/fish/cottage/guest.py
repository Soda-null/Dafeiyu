"""He comes over (decision 41): to her cottage for dinner, or just to sit. He says when he comes
and when he goes (`fish home`, or in a chat "我到你家门口了" / "我先回去了"); the room keeps it in
`guest`. While he is there: meals are for two, she is not texting him or busy with her own free
time, and what they say is said face to face. Time sees him in and out (`_guest_step`)."""

from __future__ import annotations

import re
from datetime import datetime, time

from fish.config import owner_words
from fish.cottage.rules import MEALS
from fish.cottage.state import Change, Room, _iso

LATEST = time(23, 30)  # he stays until he says he goes, at the latest this (her bed is at midnight)


# His line says he is off home ("我先回去啦", "到家了"): with him at her place, that is him leaving
# even when her reply forgets to say so (10-29 trial: home at 21:00, still "in her room").
LEAVING = re.compile(r"我?先回去|我回去了|回去啦|先走了|我走了|到家了|回家了")


def leaving_words(text: str) -> bool:
    return LEAVING.search(text) is not None


class GuestMixin:
    """Part of Cottage (room.py): him at her place. Uses the room's load / save / note."""

    def expect(self, now: datetime, since: datetime | None = None, until: datetime | None = None,
               why: str = "") -> str:
        """He is coming: now, or at `since` later today. He stays until he says he goes, or until
        `until` when he says when (at the latest LATEST: an evening trial sent him home at 20:00
        while he was still at the table). Arriving early on a visit he had planned keeps what he
        had said about it. Returns what the room noted."""
        room = self.load(now)
        planned = room.guest if room.guest and not room.guest.get("here") else {}
        since = max(since or now, now)
        from_plan = until is None and bool(planned)
        if from_plan:
            until = datetime.fromisoformat(planned["until"])
        latest = datetime.combine(since.date(), LATEST)
        said = planned.get("said", False) if from_plan else bool(until and since < until <= latest)
        until = until if until and since < until <= latest else latest
        why = why.strip()[:20] or planned.get("why", "")
        # "said": he named the hour; LATEST is only the room's own limit, never told to her as his
        # (10-29 trial: "说好待到十一点半的呢" when he got up to go at 20:30)
        room.guest = {"since": _iso(since), "until": _iso(until), "why": why, "here": False, "said": said}
        if since <= now:
            line = self._arrive(room, now)
        else:
            line = owner_words(f"他说 {since:%H:%M} 过来" + (f"（{room.guest['why']}）" if room.guest["why"] else ""))
            self.note(room, now, line)
        self.save(room)
        return line

    def send_off(self, now: datetime) -> str | None:
        """He goes home now. None when he was not there (or not yet come: the plan is off)."""
        room = self.load(now)
        if not room.guest:
            return None
        line = owner_words("他回去了") if room.guest.get("here") else owner_words("他说不过来了")
        room.guest = {}
        self.note(room, now, line)
        self.save(room)
        return line

    @staticmethod
    def waiting_for_him(room: Room, now: datetime) -> bool:
        """He said he is coming before this mealtime is over: she cooks when he is here, not
        alone at the start of the window."""
        g = room.guest
        if not g or g.get("here"):
            return False
        since = datetime.fromisoformat(g["since"])
        end = next((e for _, s, e in MEALS if s <= now.time() < e), None)
        return end is not None and since.date() == now.date() and since.time() < end

    @staticmethod
    def guest_here(room: Room, now: datetime) -> bool:
        g = room.guest
        return bool(g) and g.get("here", False) and now < datetime.fromisoformat(g["until"])

    def _arrive(self, room: Room, at: datetime, change: Change | None = None) -> str:
        room.guest["here"] = True
        why = room.guest.get("why")
        stay = f"，说待到 {room.guest['until'][11:16]}" if room.guest.get("said", True) else ""
        line = owner_words("他来了" + (f"（{why}）" if why else "") + stay)
        self.note(room, at, line, change)
        return line

    def _guest_step(self, room: Room, now: datetime, change: Change) -> None:
        """Time sees him in at the hour he said, and out at the hour he leaves."""
        g = room.guest
        if not g:
            return
        if not g.get("here") and datetime.fromisoformat(g["since"]) <= now:
            self._arrive(room, datetime.fromisoformat(g["since"]), change)
        if g.get("here") and datetime.fromisoformat(g["until"]) <= now:
            self.note(room, datetime.fromisoformat(g["until"]), owner_words("他回去了"), change)
            room.guest = {}

    @staticmethod
    def guest_line(room: Room) -> str:
        """What she sees of him: here, or coming later; "" when neither."""
        g = room.guest
        if not g:
            return ""
        said = g.get("said", True)
        why = f"，{g['why']}" if g.get("why") else ""
        if g.get("here"):
            stay = f"，说待到 {g['until'][11:16]}" if said else ""
            return owner_words(f"他这会儿就在你屋里（{g['since'][11:16]} 来的{stay}{why}）")
        about = "，".join(x for x in (f"待到 {g['until'][11:16]}" if said else "", g.get("why", "")) if x)
        return owner_words(f"他说 {g['since'][11:16]} 过来" + (f"（{about}）" if about else ""))

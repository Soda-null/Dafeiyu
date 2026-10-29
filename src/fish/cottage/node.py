"""The cottage as a node (docs/nodes_design_zh.md step 4). On every tick the room moves on
with time, and the node says on the bus what that did: how she feels (MoodMoved), a meal
eaten (SheAte), a sleep slept (SheSlept), and every new line in the room's record
(HomeEvent), including ones written while it was not looking (`fish cottage put` runs as its
own program, and a restart forgets what was said before).

"What happened lately" is a question, not a stream, so it is a service (`lately`): asking
reads the room's own record, which nothing can miss.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fish.bus import Bus
from fish.cottage.room import Cottage
from fish.msgs import HomeEvent, MoodMoved, SheAte, SheSlept, TimePassed


class RoomNode:
    def __init__(self, bus: Bus, cottage: Cottage) -> None:
        self.bus = bus
        self.cottage = cottage
        self.told: set[tuple[str, str]] = set()  # (ts, line) of record lines already said on the bus

    def on_time(self, m: TimePassed) -> None:
        self.step(m.now)

    def step(self, now: datetime) -> None:
        """Bring the room up to now and say what it did. A file he broke by hand leaves it be."""
        try:
            change = self.cottage.advance(now)
            events = self.cottage.load(now).events
        except ValueError:
            return
        if change.hunger or change.energy:
            self.bus.publish(MoodMoved(now, hunger=change.hunger, energy=change.energy, why="小屋"))
        for at, hunger in change.ate:
            self.bus.publish(SheAte(at, hunger))
        for start, end in change.slept:
            self.bus.publish(SheSlept(start, end))
        for e in events:
            key = (e["ts"], e["line"])
            if key not in self.told:
                self.bus.publish(HomeEvent(e["line"], datetime.fromisoformat(e["ts"]), bool(e.get("routine"))))
        self.told = {(e["ts"], e["line"]) for e in events}

    def lately(self, now: datetime, within: timedelta) -> list[str]:
        """What happened at home in the last `within`, meals eaten on time left out (they are
        not news: the 10-28 trial texted "饭做好了" twice a day). What happened this very
        minute counts."""
        try:
            return self.cottage.between(now - within, now + timedelta(minutes=1), routine=False)
        except ValueError:
            return []

    def view(self, now: datetime, hunger: float, energy: float | None = None) -> str:
        """The few lines of the room she sees in a chat turn, and what she could start now;
        "" when the file is broken."""
        try:
            text = self.cottage.for_chat(now, hunger)
            menu = self.cottage.menu_for_chat(now, hunger, energy) if energy is not None else ""
        except ValueError:
            return ""
        return text + ("\n" + menu if menu else "")

    def record(self, now: datetime) -> str:
        """The whole room as it is and everything that happened in it these two days: what the
        checker holds her words against (decision 38; "牛奶是你放的" was cut on the next morning
        when only today was shown). "" when the file is broken."""
        try:
            room = self.cottage.load(now)
            doing = self.cottage.doing_line(room, now=now) or "你在家，没在忙什么"
            lines = [f"此刻：{doing}", *(f"- {x}" for x in self.cottage.lines(room).values()), "这两天屋里发生的："]
            lines += [f"- {e['ts'][5:16].replace('T', ' ')} {e['line']}" for e in room.events] or ["- （还什么都没有）"]
        except ValueError:
            return ""
        return "\n".join(lines)

    def act(self, key: str, now: datetime, arg: str = "") -> bool:
        """She starts something because she said so in a chat (decision 35). The room's rules
        decide whether it can be done and what comes of it; what it costs her goes out as a
        MoodMoved. False when the room does not allow it now."""
        try:
            change = self.cottage.act(key, now, arg)
        except (ValueError, KeyError):
            return False
        if change is None:
            return False
        if change.hunger or change.energy:
            self.bus.publish(MoodMoved(now, hunger=change.hunger, energy=change.energy, why="家务"))
        return True

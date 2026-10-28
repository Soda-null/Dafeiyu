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

    def view(self, now: datetime, hunger: float) -> str:
        """The few lines of the room she sees in a chat turn; "" when the file is broken."""
        try:
            return self.cottage.for_chat(now, hunger)
        except ValueError:
            return ""

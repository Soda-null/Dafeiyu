"""The clock node (docs/nodes_design_zh.md §2): every tick it publishes TimePassed, and when a
tick crosses 03:30, where her day ends, DayEnded for the day that just finished.

Every tick is published, even one at the same moment as the last or before it (tests set the
clock by hand; each subscriber decides what a repeated moment means, as the cottage already
does). A day ends only when the clock moves forward across 03:30.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fish.bus import Bus
from fish.msgs import DayEnded, TimePassed

DAY_STARTS = time(3, 30)  # her day runs 03:30 to 03:30 (routines/nightly.py NIGHT_BOUNDARY)


def day_of(ts: datetime) -> date:
    """The day a moment belongs to: 01:00 on the 28th is still the 27th."""
    return ts.date() if ts.time() >= DAY_STARTS else ts.date() - timedelta(days=1)


class Clock:
    def __init__(self, bus: Bus) -> None:
        self.bus = bus
        self.last: datetime | None = None
        self.ended: date | None = None  # the latest day already announced over: never twice

    def tick(self, now: datetime) -> None:
        since, self.last = self.last, now
        self.bus.publish(TimePassed(now, since))
        if since is not None and now > since:
            # every day that ended between the two ticks, oldest first (a laptop asleep for two nights)
            day = day_of(since)
            if self.ended is not None:
                day = max(day, self.ended + timedelta(days=1))
            while day < day_of(now):
                self.ended = day
                self.bus.publish(DayEnded(day, now))
                day += timedelta(days=1)

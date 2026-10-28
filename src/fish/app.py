"""The launch file (docs/nodes_design_zh.md, step 3): the one place that says which node
listens to what, and in what order. A new node that reacts to time or to her words is one
line here; no other file changes.

Imports only the bus and the messages: the nodes come in as arguments, so this file knows
what they do, never how.
"""

from __future__ import annotations

from typing import Any, Callable

from fish.bus import Bus
from fish.msgs import MoodMoved, SheSaid, TimePassed


def wire(bus: Bus, *, room: Any | None, mood: Any, reach: Any, leisure: Any,
         chat: Callable[[SheSaid], None]) -> None:
    # how she feels moves only when something says it moved: the room, a free moment (step 4)
    bus.subscribe(MoodMoved, mood.on_moved)
    # every tick, in this order: time moves her room (which says what that did to her); then she
    # may think of him and text him; then, unless she just did, she may have a free moment
    if room is not None:  # no cottage (FISH_COTTAGE=0): nothing moves with time but her
        bus.subscribe(TimePassed, room.on_time)
    bus.subscribe(TimePassed, reach.on_time)
    bus.subscribe(TimePassed, leisure.on_time)
    # a line she said first: the chat keeps it; her free time knows she was busy texting
    bus.subscribe(SheSaid, chat)
    bus.subscribe(SheSaid, leisure.on_she_said)

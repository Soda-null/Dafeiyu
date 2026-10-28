"""The messages nodes pass to each other (docs/nodes_design_zh.md §3): the contract.

Like ROS .msg files: a node publishes one of these on the bus and does not know who listens;
the topic is the message's class. Fields may be added; an existing field never changes its
meaning. No imports from the rest of the package, so every node can use this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class HeSaid:
    """He sent a line (with a picture or a file, sometimes)."""
    text: str
    at: datetime
    channel: str
    image: bytes | None = None
    file_name: str = ""
    file_data: bytes | None = None


@dataclass(frozen=True)
class SheSaid:
    """She said a line; first=True when she spoke first (decisions 10, 31)."""
    text: str
    at: datetime
    channel: str
    first: bool = False
    sticker: str = ""  # path of the sticker sent after the text, "" when none
    asked: tuple[int, ...] = ()  # follow-ups this line asks about (they are done once asked)


@dataclass(frozen=True)
class SheNoted:
    """What she jotted down this turn, as the model gave it: notes, follow-ups, corrections."""
    at: datetime
    notes: tuple[dict, ...] = ()
    followups: tuple[dict, ...] = ()
    corrections: tuple[dict, ...] = ()


@dataclass(frozen=True)
class TimePassed:
    """The clock moved (every poll). `since` is the previous tick, None on the first."""
    now: datetime
    since: datetime | None = None


@dataclass(frozen=True)
class DayEnded:
    """Her day `day` is over: 03:30 came (the nightly routine's moment)."""
    day: date
    now: datetime


@dataclass(frozen=True)
class HomeEvent:
    """Something happened in her cottage; routine=True for a meal eaten on time."""
    line: str
    at: datetime
    routine: bool = False


@dataclass(frozen=True)
class MoodMoved:
    """Something moved how she feels: hours awake, a meal, a nap, a chore, a free moment.
    Deltas, added by the mood node one after another, each kept within 0–100."""
    at: datetime
    hunger: float = 0.0
    energy: float = 0.0
    boredom: float = 0.0
    why: str = ""


@dataclass(frozen=True)
class SheAte:
    at: datetime
    hunger: float  # how much it took off, negative


@dataclass(frozen=True)
class SheSlept:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class SheDid:
    """One of her free moments: what she picked and what came of it."""
    at: datetime
    what: str  # the activity's key, or "nothing"
    line: str = ""
    result: str = ""


@dataclass(frozen=True)
class MemoryChanged:
    """Memories were written or rewritten; for logs now, for a screen later."""
    at: datetime
    ids: tuple[int, ...] = field(default_factory=tuple)
    why: str = ""

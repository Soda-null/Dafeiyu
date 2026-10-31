"""What an urge is made of (decision 46), and what the urges look at to find them."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from fish.mood import Mood

HIM = "him"  # an urge to text him; any other `about` is something to do (a cottage action key)


@dataclass(frozen=True)
class Urge:
    about: str  # HIM, or what she would do ("lake")
    source: str  # which block it came from ("seen", "silence", ...)
    line: str  # why, in one line, as she is told it
    strength: float = 1.0  # how much she wants it, 0 to 1
    ref: object = None  # what it is about, when she may use it: a Memory, a Followup, a day count


@dataclass(frozen=True)
class Scene:
    """What the urges look at: her memory, how she feels, what happened at home lately, what
    she already told him (the reach-out ledger's shared ids), and where she has been."""
    conn: sqlite3.Connection
    now: datetime
    mood: Mood
    home: tuple[str, ...] = ()
    shared: frozenset[int] = field(default_factory=frozenset)
    been: dict = field(default_factory=dict)  # her cottage: when she was last back from each place, and "since" (decision 46)

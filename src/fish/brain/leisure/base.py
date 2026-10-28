"""What an activity is: something she may do in a free moment (decision 24).

An activity offers menu lines (`offer`) and, if she picks one, fetches what she ends up
looking at (`do`). It never decides whether she does it and never writes about him; the
free-moment loop in `free.py` asks her, has her write what she thought, and keeps the log.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from fish.memory import MemoryStore, Pastimes
from fish.world import Fetch, Item, Searcher


@dataclass(frozen=True)
class Choice:
    activity: str  # the key of the activity that handles it
    line: str  # what she sees in the menu: plain words, nothing that sells it
    details: tuple[str, ...] = ()  # sub-items she may pick by number (headlines)
    arg_hint: str = ""  # set when she must say something to do it (a title, a word)
    payload: dict = field(default_factory=dict, hash=False, compare=False)  # the activity's own


@dataclass
class Material:
    """What came of a choice: pages to look at, or one line when there is nothing to read."""
    opened: list[tuple[Item, str]] = field(default_factory=list)
    result: str = ""  # one line for the log and her diary: "读了《西遊記》第001回的前一段"


@dataclass
class Kit:
    """What every activity may use."""
    conn: sqlite3.Connection
    now: datetime
    store: MemoryStore
    pastimes: Pastimes
    fetch: Fetch
    searcher: Searcher | None
    sources: list[dict]


class Activity:
    key = ""

    def offer(self, kit: Kit) -> list[Choice]:
        return []

    def do(self, kit: Kit, choice: Choice, picks: list[int], arg: str) -> Material:
        raise NotImplementedError

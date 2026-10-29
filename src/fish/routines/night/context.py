"""What one night's steps share: the day being closed, the stores, and what earlier steps found
for later ones (today's new notes, what was merged away, the diary's phase sentence, the phase)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from fish.bus import Bus
from fish.memory import EpisodeManager, Memory, MemoryStore, Phase, PhaseStore, Relationship
from fish.mood import MoodStore

if TYPE_CHECKING:
    from fish.brain import Brain, Consolidator

NIGHT_BOUNDARY = time(3, 30)


def fish_day(ts: datetime) -> date:
    return ts.date() if ts.time() >= NIGHT_BOUNDARY else ts.date() - timedelta(days=1)


def diary_day(now: datetime) -> date:
    """The day the night closes: yesterday once the boundary has passed."""
    return fish_day(now) - timedelta(days=1)


@dataclass
class Night:
    conn: sqlite3.Connection
    now: datetime
    day: date
    bus: Bus
    brain: "Brain | None"
    thinker: "Consolidator | None"  # None without a brain: only the mechanical steps run
    export_path: Path | None
    store: MemoryStore
    episodes: EpisodeManager
    moods: MoodStore
    phases: PhaseStore
    rel: Relationship
    report: dict
    new: list[Memory] = field(default_factory=list)  # notes written today (take_stock)
    merged_away: set[int] = field(default_factory=set)  # merged tonight, not candidates after
    line: str | None = None  # the diary's sentence for "这阵子的你" (diary -> phase)
    phase: Phase | None = None  # tonight's phase (phase -> sleep)

    @property
    def day_start(self) -> datetime:
        return datetime.combine(self.day, NIGHT_BOUNDARY)

    @property
    def day_end(self) -> datetime:
        return datetime.combine(self.day + timedelta(days=1), NIGHT_BOUNDARY)

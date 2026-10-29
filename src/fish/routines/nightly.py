"""Nightly routine (docs/memory_design_zh.md §5.4), once per "fish day".

Her day ends at NIGHT_BOUNDARY (03:30): a chat at 01:00 on the 27th still belongs to the
26th. `diary_day(now)` is the day being closed; `routine_runs.nightly` holds the last one
done, so the 03:30 timer and a catch-up at the next start never do the same day twice.

The night is wired like the day (docs/nodes_design_zh.md step 5): one DayEnded goes out on a
bus of its own, and each step below hears it, in this order, with the night's shared notebook
(night/context.py). A step that fails does not stop the ones after it; the failure is raised
when the night is done. Model steps need a Brain; without one only the mechanical ones run.
To do something new at night: write a step in night/, add it to NIGHT_STEPS.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from fish.brain import Consolidator
from fish.bus import Bus
from fish.memory import EpisodeManager, MemoryStore, PhaseStore, Relationship
from fish.mood import MoodNode, MoodStore
from fish.msgs import DayEnded, Rested
from fish.routines.night import diary, reflect, tidy, upkeep
from fish.routines.night.context import NIGHT_BOUNDARY, Night, diary_day, fish_day
from fish.routines.night.diary import GROWTH_EVERY_DAYS, SELF_NOTES_PER_NIGHT, strongest
from fish.routines.night.reflect import REFLECT_AFTER_EPISODES, REFLECT_EVERY_DAYS
from fish.routines.night.tidy import (MAX_CANDIDATES, MAX_PAIRS, MERGE_SIMILARITY, _change_groups, _merge_pairs,
                                      _new_today, _update_groups)
from fish.routines.runs import claim_run, last_run

if TYPE_CHECKING:
    from fish.brain import Brain

EXPORT_PATH = Path("data/notebook_export.md")

# The night, in order. Later steps read what earlier ones left in the notebook: take_stock's
# new notes for the merge and the updates, the merge's ids for the updates, the diary's
# sentence for the phase, the phase for sleep.
NIGHT_STEPS: list[Callable[[Night], None]] = [
    tidy.close_trailing_chat,    # 1
    tidy.take_stock,
    tidy.merge_duplicates,       # 2
    tidy.replace_old_facts,      # 3, 3a
    tidy.gist_repeats,           # 3b
    reflect.look_back,           # 4
    diary.write_diary,           # 5
    diary.step_phase,            # 5b
    diary.look_at_herself,       # 5c
    upkeep.sleep,                # 6
    upkeep.compress_old_chats,
    upkeep.count_weekday_habits,  # 6b
    upkeep.let_go_of_unasked,    # 7
    upkeep.export,               # 8
    upkeep.caption_stickers,     # 9
]

__all__ = ["EXPORT_PATH", "GROWTH_EVERY_DAYS", "MAX_CANDIDATES", "MAX_PAIRS", "MERGE_SIMILARITY",
           "NIGHT_BOUNDARY", "NIGHT_STEPS", "REFLECT_AFTER_EPISODES", "REFLECT_EVERY_DAYS", "SELF_NOTES_PER_NIGHT",
           "Night", "_change_groups", "_merge_pairs", "_new_today", "_update_groups", "diary_day", "fish_day",
           "run_nightly", "strongest"]


def _hearing(step: Callable[[Night], None], night: Night) -> Callable[[DayEnded], None]:
    """The step as a subscriber, named after it, so a failure says which step it was."""
    def on_day_ended(m: DayEnded) -> None:
        step(night)
    on_day_ended.__qualname__ = f"night.{step.__name__}"
    return on_day_ended


def run_nightly(conn: sqlite3.Connection, now: datetime | None = None, *,
                brain: "Brain | None" = None, export_path: Path | None = None) -> dict:
    now = now or datetime.now()
    day = diary_day(now)
    if last_run(conn, "nightly") == day.isoformat() or not claim_run(conn, "nightly", day.isoformat()):
        return {"skipped": True}
    bus = Bus()
    moods = MoodStore(conn)
    night = Night(conn=conn, now=now, day=day, bus=bus, brain=brain,
                  thinker=Consolidator(brain.llm, brain.persona) if brain else None,
                  export_path=export_path, store=MemoryStore(conn), episodes=EpisodeManager(conn),
                  moods=moods, phases=PhaseStore(conn), rel=Relationship(conn),
                  report={"skipped": False, "day": day.isoformat()})
    bus.subscribe(Rested, MoodNode(moods).on_rested)  # her morning is the mood node's to set
    for step in NIGHT_STEPS:
        bus.subscribe(DayEnded, _hearing(step, night))
    bus.publish(DayEnded(day, now))
    return night.report

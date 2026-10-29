"""Her mood as a node (docs/nodes_design_zh.md step 4): it changes only when a message says
something moved it. Nobody else writes her hunger, energy or boredom from outside."""

from __future__ import annotations

from fish.mood.state import MoodStore
from fish.msgs import Chatted, MoodMoved, Rested

KEYS = ("hunger", "energy", "boredom")


class MoodNode:
    def __init__(self, store: MoodStore, *, kitchen: bool = False) -> None:
        self.store = store
        self.kitchen = kitchen  # with her cottage, talking moves neither hunger nor energy (decision 32)

    def on_chatted(self, m: Chatted) -> None:
        """How one exchange moves her, and the line in the day's mood log the night reads."""
        base = MoodStore.after_turn(self.store.load(), m.he, m.she, reported=m.mood, topic=m.topic,
                                    last_topic=m.last_topic, kitchen=self.kitchen)
        self.store.save(base)
        self.store.log(base, m.mood, m.at)

    def on_moved(self, m: MoodMoved) -> None:
        base = self.store.load()
        for key in KEYS:
            delta = getattr(m, key)
            if delta:
                setattr(base, key, min(100.0, max(0.0, getattr(base, key) + delta)))
        self.store.save(base)

    def on_rested(self, m: Rested) -> None:
        self.store.rest(tone=m.tone, drive=m.drive)

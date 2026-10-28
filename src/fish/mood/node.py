"""Her mood as a node (docs/nodes_design_zh.md step 4): it changes only when a message says
something moved it. Nobody else writes her hunger, energy or boredom from outside."""

from __future__ import annotations

from fish.mood.state import MoodStore
from fish.msgs import MoodMoved

KEYS = ("hunger", "energy", "boredom")


class MoodNode:
    def __init__(self, store: MoodStore) -> None:
        self.store = store

    def on_moved(self, m: MoodMoved) -> None:
        base = self.store.load()
        for key in KEYS:
            delta = getattr(m, key)
            if delta:
                setattr(base, key, min(100.0, max(0.0, getattr(base, key) + delta)))
        self.store.save(base)

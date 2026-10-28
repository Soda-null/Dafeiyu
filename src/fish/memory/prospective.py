"""Prospective memory: things she means to ask him on a given day (§5.7)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from fish.memory.longterm import iso
from fish.memory.retrieval import BigramEmbedder

# A friend keeps a few things in mind, asks within a day or so, and lets the rest go (decision 17).
GRACE_DAYS = 1  # an open follow-up this many days past due is given up on
MAX_OPEN = 5  # no new follow-up while this many are open
SAME_AS = 0.5  # bigram overlap at which a new follow-up repeats an open one
DUE_SHOWN = 2  # due follow-ups offered to her in one turn


@dataclass(frozen=True)
class Followup:
    id: int
    text: str
    due: str  # YYYY-MM-DD
    created: str
    source_memory: int | None
    status: str  # open | asked | expired


def _overlap(a: str, b: str) -> float:
    x, y = BigramEmbedder.bigrams(a), BigramEmbedder.bigrams(b)
    return 2 * len(x & y) / (len(x) + len(y)) if x and y else 0.0


def _from_row(r: sqlite3.Row) -> Followup:
    return Followup(r["id"], r["text"], r["due"], r["created"], r["source_memory"], r["status"])


class ProspectiveStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add(self, text: str, due: str, *, source_memory: int | None = None,
            now: datetime | None = None) -> Followup | None:
        """None when she already has enough on her mind, or already means to ask this."""
        now = now or datetime.now()
        held = self.open()
        if len(held) >= MAX_OPEN or any(_overlap(text, f.text) >= SAME_AS for f in held):
            return None
        cur = self.conn.execute(
            "INSERT INTO prospective (text, due, created, source_memory, status)"
            " VALUES (?, ?, ?, ?, 'open')",
            (text, due, iso(now), source_memory),
        )
        self.conn.commit()
        return self.get(cur.lastrowid)

    def get(self, followup_id: int) -> Followup:
        row = self.conn.execute("SELECT * FROM prospective WHERE id = ?", (followup_id,)).fetchone()
        if row is None:
            raise KeyError(f"no follow-up {followup_id}")
        return _from_row(row)

    def open(self) -> list[Followup]:
        rows = self.conn.execute("SELECT * FROM prospective WHERE status = 'open' ORDER BY due, id")
        return [_from_row(r) for r in rows]

    def due(self, now: datetime | None = None) -> list[Followup]:
        """Open follow-ups whose day has come: these go into the prompt as '你想问他的'."""
        today = (now or datetime.now()).date().isoformat()
        rows = self.conn.execute(
            "SELECT * FROM prospective WHERE status = 'open' AND due <= ? ORDER BY due, id", (today,)
        )
        return [_from_row(r) for r in rows]

    def close(self, followup_id: int, status: str = "asked") -> None:
        self.conn.execute("UPDATE prospective SET status = ? WHERE id = ?", (status, followup_id))
        self.conn.commit()

    def expire(self, now: datetime | None = None, grace_days: int = GRACE_DAYS) -> list[Followup]:
        """Nightly: give up on follow-ups she never got to ask; returns them. They are only closed,
        never turned into memories (memory v3). One about a promise still open between them
        ("去海边了没") is never given up: the promise has no day it runs out."""
        cutoff = ((now or datetime.now()).date() - timedelta(days=grace_days)).isoformat()
        rows = self.conn.execute(
            "SELECT * FROM prospective p WHERE status = 'open' AND due < ? AND NOT EXISTS"
            " (SELECT 1 FROM memories m WHERE m.id = p.source_memory AND m.superseded_by IS NULL"
            "  AND m.pact_state = 'open') ORDER BY due, id", (cutoff,)
        ).fetchall()
        expired = [_from_row(r) for r in rows]
        for f in expired:
            self.close(f.id, "expired")
        return expired

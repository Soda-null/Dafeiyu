"""Prospective memory: things she means to ask him on a given day (§5.7)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from fish.memory.longterm import iso

GRACE_DAYS = 3  # an open follow-up this many days past due is given up on


@dataclass(frozen=True)
class Followup:
    id: int
    text: str
    due: str  # YYYY-MM-DD
    created: str
    source_memory: int | None
    status: str  # open | asked | expired


def _from_row(r: sqlite3.Row) -> Followup:
    return Followup(r["id"], r["text"], r["due"], r["created"], r["source_memory"], r["status"])


class ProspectiveStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add(self, text: str, due: str, *, source_memory: int | None = None,
            now: datetime | None = None) -> Followup:
        now = now or datetime.now()
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
        """Nightly: give up on follow-ups she never got to ask; returns them so they can become events."""
        cutoff = ((now or datetime.now()).date() - timedelta(days=grace_days)).isoformat()
        rows = self.conn.execute(
            "SELECT * FROM prospective WHERE status = 'open' AND due < ? ORDER BY due, id", (cutoff,)
        ).fetchall()
        expired = [_from_row(r) for r in rows]
        for f in expired:
            self.close(f.id, "expired")
        return expired

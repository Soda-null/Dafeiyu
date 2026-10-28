"""Diary: one short entry per day about her own (invented) life."""

from __future__ import annotations

import sqlite3

from fish.memory.scrub import redact


class Diary:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def write(self, day: str, text: str) -> None:
        """A sentence that holds a secret is left out (scrub.py)."""
        self.conn.execute(
            "INSERT OR REPLACE INTO diary (day, text) VALUES (?, ?)", (day, redact(text))
        )
        self.conn.commit()

    def recent(self, days: int = 3) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT day, text FROM diary ORDER BY day DESC LIMIT ?", (days,)
        ).fetchall()
        return [(r["day"], r["text"]) for r in reversed(rows)]

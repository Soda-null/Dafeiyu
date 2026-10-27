"""The relationship ledger: when they met, how many days they have talked, the streak, and
closeness, which moves over days (decision 13 put it here, out of the hour-scale mood)."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from fish.memory.longterm import iso

CLOSENESS_START = 10.0
CLOSENESS_PER_TURN = 0.5
CLOSENESS_WHEN_HAPPY = 2.0
CLOSENESS_DECAY_PER_QUIET_DAY = 1.0


class Relationship:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # --- closeness ---------------------------------------------------------------

    @property
    def closeness(self) -> float:
        value = self.get("closeness")
        if value is None:  # before decision 13 closeness lived in the mood table; carry it over once
            row = self.conn.execute("SELECT value FROM mood WHERE key = 'closeness'").fetchone()
            value = str(row["value"]) if row else str(CLOSENESS_START)
            self.set("closeness", value)
        return float(value)

    def set_closeness(self, value: float, now: datetime | None = None) -> float:
        value = max(0.0, min(100.0, value))
        self.set("closeness", f"{value:.2f}", now)
        return value

    def bump_closeness(self, reported: str | None, now: datetime | None = None) -> float:
        step = CLOSENESS_WHEN_HAPPY if reported == "开心" else CLOSENESS_PER_TURN
        return self.set_closeness(self.closeness + step, now)

    def quiet_day(self, now: datetime | None = None) -> float:
        """A day without him: a little less close."""
        return self.set_closeness(self.closeness - CLOSENESS_DECAY_PER_QUIET_DAY, now)

    def get(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM relationship WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set(self, key: str, value: str, now: datetime | None = None) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO relationship (key, value, updated) VALUES (?, ?, ?)",
            (key, value, iso(now or datetime.now())),
        )
        self.conn.commit()

    def note_active_day(self, now: datetime | None = None) -> None:
        """Call once per message. Sets first_met, counts talked days, keeps the streak."""
        now = now or datetime.now()
        today = now.date()
        if self.get("first_met") is None:
            self.set("first_met", today.isoformat(), now)
        last = self.get("last_day")
        if last == today.isoformat():
            return
        streak = int(self.get("streak", "0") or 0)
        streak = streak + 1 if last == (today - timedelta(days=1)).isoformat() else 1
        self.set("streak", str(streak), now)
        self.set("days_talked", str(int(self.get("days_talked", "0") or 0) + 1), now)
        self.set("last_day", today.isoformat(), now)

    def days_known(self, now: datetime | None = None) -> int:
        first = self.get("first_met")
        if first is None:
            return 0
        return ((now or datetime.now()).date() - date.fromisoformat(first)).days + 1

    def stats(self, now: datetime | None = None) -> dict[str, int]:
        return {
            "days_known": self.days_known(now),
            "days_talked": int(self.get("days_talked", "0") or 0),
            "streak": int(self.get("streak", "0") or 0),
        }

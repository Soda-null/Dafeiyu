"""The relationship ledger: when they met, how many days they have talked, the streak, and
closeness, which moves over days (decision 13 put it here, out of the hour-scale mood)."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta

from fish.memory.longterm import iso

CLOSENESS_START = 10.0
CLOSENESS_PER_TURN = 0.3
CLOSENESS_WHEN_HAPPY = 1.0
# Friends are made over days, not messages (decision 17): one day of talk adds at most this
# much, less once they are close. Talking daily: 熟了 after about a week, 很熟 after about six.
DAILY_CAP = ((60.0, 0.8), (25.0, 1.0), (0.0, 2.0))  # (closeness from, most gained per day)
CLOSENESS_DECAY_PER_QUIET_DAY = 0.5


def daily_cap(closeness: float) -> float:
    return next(cap for floor, cap in DAILY_CAP if closeness >= floor)


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
        """One turn's worth, until today's cap is used up."""
        now = now or datetime.now()
        today = now.date().isoformat()
        gained = float(self.get("closeness_gained", "0") or 0) if self.get("closeness_day") == today else 0.0
        step = CLOSENESS_WHEN_HAPPY if reported == "开心" else CLOSENESS_PER_TURN
        step = min(step, daily_cap(self.closeness) - gained)
        if step <= 0:
            return self.closeness
        self.set("closeness_day", today, now)
        self.set("closeness_gained", f"{gained + step:.2f}", now)
        return self.set_closeness(self.closeness + step, now)

    def quiet_day(self, now: datetime | None = None) -> float:
        """A day without him: a little less close."""
        return self.set_closeness(self.closeness - CLOSENESS_DECAY_PER_QUIET_DAY, now)

    # --- weekday patterns (memory v3 §B6), counted at night by patterns.py ------------------

    def patterns(self) -> list[dict]:
        try:
            value = json.loads(self.get("patterns") or "[]")
        except ValueError:
            return []
        return value if isinstance(value, list) else []

    def set_patterns(self, patterns: list[dict], now: datetime | None = None) -> None:
        self.set("patterns", json.dumps(patterns, ensure_ascii=False), now)

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

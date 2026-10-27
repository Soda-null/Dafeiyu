"""Layer B of her character (decision 13): how she has been these days.

Two slow numbers and a sentence. `tone` (-1..1) and `drive` (0..1) move each night by a
fifth of the way toward what the day showed, so one bad evening nudges them and only a
run of days turns them. `focus` is what she is into lately; `line` is the sentence she
sees about herself in every chat.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

INERTIA = 0.8  # share of yesterday kept each night
DEFAULT_TONE, DEFAULT_DRIVE = 0.1, 0.6


@dataclass(frozen=True)
class Phase:
    day: str
    tone: float
    drive: float
    focus: tuple[str, ...]
    line: str

    @property
    def tone_word(self) -> str:
        return "偏好" if self.tone > 0.3 else "偏低" if self.tone < -0.3 else "一般"

    @property
    def drive_word(self) -> str:
        return "挺有劲" if self.drive > 0.7 else "有点蔫" if self.drive < 0.4 else "还行"


def _from_row(r: sqlite3.Row) -> Phase:
    return Phase(r["day"], r["tone"], r["drive"], tuple(json.loads(r["focus"] or "[]")), r["line"] or "")


class PhaseStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def current(self) -> Phase:
        row = self.conn.execute("SELECT * FROM phase ORDER BY day DESC LIMIT 1").fetchone()
        return _from_row(row) if row else Phase("", DEFAULT_TONE, DEFAULT_DRIVE, (), "")

    def history(self, days: int = 30) -> list[Phase]:
        rows = self.conn.execute("SELECT * FROM phase ORDER BY day DESC LIMIT ?", (days,)).fetchall()
        return [_from_row(r) for r in reversed(rows)]

    def update(self, day: str, *, tone_today: float | None, drive_today: float | None,
               focus: list[str] | None = None, line: str | None = None) -> Phase:
        """One night's step: keep INERTIA of yesterday, take the rest from today.
        A day with no data leaves the numbers where they were."""
        prev = self.current()
        tone = prev.tone if tone_today is None else INERTIA * prev.tone + (1 - INERTIA) * tone_today
        drive = prev.drive if drive_today is None else INERTIA * prev.drive + (1 - INERTIA) * drive_today
        tone = max(-1.0, min(1.0, tone))
        drive = max(0.0, min(1.0, drive))
        new = Phase(day, tone, drive, tuple(focus if focus is not None else prev.focus),
                    line if line is not None else prev.line)
        self.conn.execute(
            "INSERT OR REPLACE INTO phase (day, tone, drive, focus, line) VALUES (?, ?, ?, ?, ?)",
            (day, tone, drive, json.dumps(list(new.focus), ensure_ascii=False), new.line),
        )
        self.conn.commit()
        return new

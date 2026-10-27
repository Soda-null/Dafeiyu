"""Episodes: one chat session each, the unit of episodic memory (§3).

A new episode starts when the last message is more than GAP_MINUTES old or on another
calendar day. Closing an episode needs a summary from the brain; this module only keeps
the records. Levels: 0 full (messages still cited), 1 summary only, 2 gist only.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from fish.memory.longterm import days_between, iso

GAP_MINUTES = 30
SUMMARY_ONLY_AFTER_DAYS = 7
GIST_ONLY_AFTER_DAYS = 30
GIST_ONLY_BELOW_IMPORTANCE = 6


@dataclass(frozen=True)
class Episode:
    id: int
    started: str
    last_active: str
    ended: str | None
    channel: str
    running_summary: str
    summary: str
    gist: str
    importance: int | None
    valence: float | None
    level: int

    @property
    def open(self) -> bool:
        return self.ended is None


def _from_row(r: sqlite3.Row) -> Episode:
    return Episode(
        r["id"], r["started"], r["last_active"], r["ended"], r["channel"],
        r["running_summary"] or "", r["summary"] or "", r["gist"] or "",
        r["importance"], r["valence"], r["level"],
    )


class EpisodeManager:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, episode_id: int) -> Episode:
        row = self.conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if row is None:
            raise KeyError(f"no episode {episode_id}")
        return _from_row(row)

    def open_episode(self) -> Episode | None:
        row = self.conn.execute(
            "SELECT * FROM episodes WHERE ended IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return _from_row(row) if row else None

    def stale(self, now: datetime | None = None) -> Episode | None:
        """The open episode if it should be closed before this message (gap or new day)."""
        now = now or datetime.now()
        ep = self.open_episode()
        if ep is None:
            return None
        last = datetime.fromisoformat(ep.last_active)
        if now - last > timedelta(minutes=GAP_MINUTES) or now.date() != last.date():
            return ep
        return None

    def start(self, channel: str, now: datetime | None = None) -> Episode:
        now = now or datetime.now()
        cur = self.conn.execute(
            "INSERT INTO episodes (started, last_active, channel, level) VALUES (?, ?, ?, 0)",
            (iso(now), iso(now), channel),
        )
        self.conn.commit()
        return self.get(cur.lastrowid)

    def touch(self, episode_id: int, now: datetime | None = None) -> None:
        self.conn.execute(
            "UPDATE episodes SET last_active = ? WHERE id = ?", (iso(now or datetime.now()), episode_id)
        )
        self.conn.commit()

    def fold_in(self, episode_id: int, running_summary: str) -> None:
        self.conn.execute(
            "UPDATE episodes SET running_summary = ? WHERE id = ?", (running_summary, episode_id)
        )
        self.conn.commit()

    def close(self, episode_id: int, *, summary: str, gist: str, importance: int,
              valence: float, now: datetime | None = None) -> Episode:
        self.conn.execute(
            "UPDATE episodes SET ended = ?, summary = ?, gist = ?, importance = ?, valence = ?"
            " WHERE id = ?",
            (iso(now or datetime.now()), summary, gist, importance, valence, episode_id),
        )
        self.conn.commit()
        return self.get(episode_id)

    def recent(self, n: int = 5) -> list[Episode]:
        rows = self.conn.execute(
            "SELECT * FROM episodes WHERE ended IS NOT NULL ORDER BY id DESC LIMIT ?", (n,)
        )
        return [_from_row(r) for r in rows]

    def compress(self, now: datetime | None = None) -> int:
        """Nightly: old episodes lose detail in two steps. Returns how many changed level."""
        now = now or datetime.now()
        changed = 0
        for ep in (_from_row(r) for r in self.conn.execute(
                "SELECT * FROM episodes WHERE ended IS NOT NULL AND level < 2")):
            age = days_between(ep.ended, now)
            level = ep.level
            if age > SUMMARY_ONLY_AFTER_DAYS and level < 1:
                level = 1
            if (age > GIST_ONLY_AFTER_DAYS and level < 2
                    and (ep.importance or 0) < GIST_ONLY_BELOW_IMPORTANCE):
                level = 2
            if level != ep.level:
                self.conn.execute("UPDATE episodes SET level = ? WHERE id = ?", (level, ep.id))
                changed += 1
        self.conn.commit()
        return changed

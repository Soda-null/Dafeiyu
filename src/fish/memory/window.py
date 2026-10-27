"""Window: her working memory. The last N unfolded turns of the current episode, verbatim.

When an episode runs past N turns, the oldest FOLD_BATCH turns are handed to the brain to be
folded into the episode's running summary and then marked folded; they stay in `messages`
forever as evidence but leave the prompt.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from fish.memory.longterm import iso

DEFAULT_SIZE = 20
FOLD_BATCH = 10


@dataclass(frozen=True)
class Turn:
    id: int
    role: str  # 'user' | 'fish'
    text: str
    ts: str


def _turns(rows) -> list[Turn]:
    return [Turn(r["id"], r["role"], r["text"], r["ts"]) for r in rows]


class Window:
    def __init__(self, conn: sqlite3.Connection, size: int = DEFAULT_SIZE,
                 fold_batch: int = FOLD_BATCH) -> None:
        self.conn = conn
        self.size = size
        self.fold_batch = fold_batch

    def append(self, role: str, text: str, channel: str, episode_id: int | None = None,
               now: datetime | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO messages (ts, role, text, channel, episode_id, folded)"
            " VALUES (?, ?, ?, ?, ?, 0)",
            (iso(now or datetime.now()), role, text, channel, episode_id),
        )
        self.conn.commit()
        return cur.lastrowid

    def recent(self, episode_id: int | None = None) -> list[Turn]:
        """The last `size` unfolded turns, oldest first; of one episode if given."""
        sql = "SELECT id, role, text, ts FROM messages WHERE folded = 0"
        args: tuple = ()
        if episode_id is not None:
            sql += " AND episode_id = ?"
            args = (episode_id,)
        rows = self.conn.execute(sql + " ORDER BY id DESC LIMIT ?", args + (self.size,)).fetchall()
        return _turns(reversed(rows))

    def to_fold(self, episode_id: int) -> list[Turn]:
        """The oldest turns to summarize away, or [] while the episode still fits."""
        count = self.conn.execute(
            "SELECT COUNT(*) FROM messages WHERE folded = 0 AND episode_id = ?", (episode_id,)
        ).fetchone()[0]
        if count <= self.size:
            return []
        rows = self.conn.execute(
            "SELECT id, role, text, ts FROM messages WHERE folded = 0 AND episode_id = ?"
            " ORDER BY id LIMIT ?",
            (episode_id, self.fold_batch),
        )
        return _turns(rows)

    def mark_folded(self, ids: list[int]) -> None:
        self.conn.executemany("UPDATE messages SET folded = 1 WHERE id = ?", [(i,) for i in ids])
        self.conn.commit()

    def last_ts(self) -> str | None:
        row = self.conn.execute("SELECT ts FROM messages ORDER BY id DESC LIMIT 1").fetchone()
        return row["ts"] if row else None

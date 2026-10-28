"""What she has going on in her free time (decision 24): bookmarks and the free-moment log.

A bookmark is a fact, not a task: the menu offers "go on reading" next to everything else.
One she has not touched for DROP_AFTER_DAYS she has let go of, like a show one stops
watching; it stays in the table so she can say she once read half of it.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from fish.memory.longterm import iso

DROP_AFTER_DAYS = 30


@dataclass(frozen=True)
class Pastime:
    id: int
    kind: str
    title: str
    ref: str
    progress: dict
    status: str  # on | dropped | finished
    started: str
    touched: str


@dataclass(frozen=True)
class Moment:
    id: int
    ts: str
    choice: str | None  # activity key or 'nothing'; None: she was asked and nothing came back
    line: str
    why: str
    result: str
    memories: tuple[int, ...]


def _pastime(r: sqlite3.Row) -> Pastime:
    return Pastime(r["id"], r["kind"], r["title"], r["ref"], json.loads(r["progress"] or "{}"),
                   r["status"], r["started"], r["touched"])


def _moment(r: sqlite3.Row) -> Moment:
    return Moment(r["id"], r["ts"], r["choice"], r["line"] or "", r["why"] or "", r["result"] or "",
                  tuple(json.loads(r["memories"] or "[]")))


class Pastimes:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # --- bookmarks -----------------------------------------------------------

    def start(self, kind: str, title: str, ref: str, progress: dict | None = None,
              now: datetime | None = None) -> Pastime:
        """Pick one up; picking up something she had dropped resumes the old bookmark."""
        now = now or datetime.now()
        old = self.conn.execute("SELECT * FROM pastimes WHERE kind = ? AND ref = ?", (kind, ref)).fetchone()
        if old is not None:
            self.conn.execute("UPDATE pastimes SET status = 'on', touched = ? WHERE id = ?", (iso(now), old["id"]))
            self.conn.commit()
            return self.get(old["id"])
        cur = self.conn.execute(
            "INSERT INTO pastimes (kind, title, ref, progress, status, started, touched)"
            " VALUES (?, ?, ?, ?, 'on', ?, ?)",
            (kind, title, ref, json.dumps(progress or {}, ensure_ascii=False), iso(now), iso(now)))
        self.conn.commit()
        return self.get(cur.lastrowid)

    def get(self, pastime_id: int) -> Pastime:
        row = self.conn.execute("SELECT * FROM pastimes WHERE id = ?", (pastime_id,)).fetchone()
        if row is None:
            raise KeyError(f"no pastime {pastime_id}")
        return _pastime(row)

    def advance(self, pastime_id: int, progress: dict, now: datetime | None = None, *,
                finished: bool = False) -> None:
        self.conn.execute("UPDATE pastimes SET progress = ?, touched = ?, status = ? WHERE id = ?",
                          (json.dumps(progress, ensure_ascii=False), iso(now or datetime.now()),
                           "finished" if finished else "on", pastime_id))
        self.conn.commit()

    def drop(self, pastime_id: int, now: datetime | None = None) -> None:
        self.conn.execute("UPDATE pastimes SET status = 'dropped', touched = ? WHERE id = ?",
                          (iso(now or datetime.now()), pastime_id))
        self.conn.commit()

    def active(self, now: datetime | None = None, kind: str | None = None) -> list[Pastime]:
        """What she is still following; untouched for a month means she let it go."""
        now = now or datetime.now()
        self.conn.execute("UPDATE pastimes SET status = 'dropped' WHERE status = 'on' AND touched < ?",
                          (iso(now - timedelta(days=DROP_AFTER_DAYS)),))
        self.conn.commit()
        sql, args = "SELECT * FROM pastimes WHERE status = 'on'", []
        if kind:
            sql, args = sql + " AND kind = ?", [kind]
        return [_pastime(r) for r in self.conn.execute(sql + " ORDER BY touched DESC", args)]

    def all(self) -> list[Pastime]:
        return [_pastime(r) for r in self.conn.execute("SELECT * FROM pastimes ORDER BY touched DESC")]

    # --- the free-moment log ---------------------------------------------------

    def begin_moment(self, now: datetime) -> int:
        """Written before she is asked, so a crash cannot make the gate ask again and again."""
        cur = self.conn.execute("INSERT INTO leisure_log (ts) VALUES (?)", (iso(now),))
        self.conn.commit()
        return cur.lastrowid

    def end_moment(self, moment_id: int, choice: str, line: str = "", why: str = "",
                   result: str = "", memories: list[int] | None = None) -> None:
        self.conn.execute("UPDATE leisure_log SET choice = ?, line = ?, why = ?, result = ?, memories = ?"
                          " WHERE id = ?", (choice, line, why, result, json.dumps(memories or []), moment_id))
        self.conn.commit()

    def moments(self, since: datetime, until: datetime | None = None) -> list[Moment]:
        sql, args = "SELECT * FROM leisure_log WHERE ts >= ?", [iso(since)]
        if until is not None:
            sql, args = sql + " AND ts < ?", args + [iso(until)]
        return [_moment(r) for r in self.conn.execute(sql + " ORDER BY ts", args)]

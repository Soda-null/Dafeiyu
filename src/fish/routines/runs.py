"""The routine_runs table: which fish day each routine last handled.

`claim_run` is atomic: when the WeChat service starts up at the same moment a manual
`fish browse` runs (it happened on 2026-10-26), only one of them gets the day.
"""

from __future__ import annotations

import sqlite3


def last_run(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute("SELECT last_run FROM routine_runs WHERE name = ?", (name,)).fetchone()
    return row["last_run"] if row else None


def mark_run(conn: sqlite3.Connection, name: str, day: str) -> None:
    conn.execute("INSERT OR REPLACE INTO routine_runs (name, last_run) VALUES (?, ?)", (name, day))
    conn.commit()


def claim_run(conn: sqlite3.Connection, name: str, day: str) -> bool:
    """True if this call took `day` for `name`; False if it was already taken."""
    with conn:  # one transaction: the check and the write cannot interleave with another process
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT last_run FROM routine_runs WHERE name = ?", (name,)).fetchone()
        if row is not None and row["last_run"] == day:
            return False
        conn.execute("INSERT OR REPLACE INTO routine_runs (name, last_run) VALUES (?, ?)", (name, day))
    return True

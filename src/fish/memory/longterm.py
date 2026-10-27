"""Long-term memories: the `memories` table and a memory's lifecycle.

add -> (recall) touch -> correct (supersede) / merge -> never deleted.
Data and math only; the text of a memory is written by the brain or the nightly routine.
Field meanings: docs/memory_design_zh.md §4.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from fish.memory import stability as st

KINDS = ("fact", "event", "howto", "insight", "self", "world")  # world: things she saw online
PROFILE_IMPORTANCE = 8  # facts at or above this importance form the always-present profile
PROFILE_SIZE = 12


def iso(now: datetime) -> str:
    return now.isoformat(timespec="seconds")


def days_between(earlier: str, now: datetime) -> float:
    return (now - datetime.fromisoformat(earlier)).total_seconds() / 86400


@dataclass(frozen=True)
class Memory:
    id: int
    kind: str
    text: str
    created: str
    source_episode: int | None
    importance: int
    valence: float
    arousal: float
    stability: float
    last_recalled: str
    recall_count: int
    superseded_by: int | None
    merged_from: tuple[int, ...]
    tags: tuple[str, ...]
    pinned: bool
    source: str | None = None  # kind=world: where she saw it

    def retrievability(self, now: datetime) -> float:
        return st.retrievability(self.stability, days_between(self.last_recalled, now))

    def fuzzy(self, now: datetime) -> bool:
        return self.retrievability(now) < st.FUZZY_R

    @property
    def alive(self) -> bool:
        return self.superseded_by is None


def _from_row(r: sqlite3.Row) -> Memory:
    return Memory(
        id=r["id"], kind=r["kind"], text=r["text"], created=r["created"],
        source_episode=r["source_episode"], importance=r["importance"],
        valence=r["valence"], arousal=r["arousal"], stability=r["stability"],
        last_recalled=r["last_recalled"], recall_count=r["recall_count"],
        superseded_by=r["superseded_by"],
        merged_from=tuple(json.loads(r["merged_from"] or "[]")),
        tags=tuple(json.loads(r["tags"] or "[]")),
        pinned=bool(r["pinned"]),
        source=r["source"] if "source" in r.keys() else None,
    )


class MemoryStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # --- write -------------------------------------------------------------

    def add(
        self,
        kind: str,
        text: str,
        *,
        importance: int,
        valence: float = 0.0,
        arousal: float = 0.0,
        source_episode: int | None = None,
        tags: tuple[str, ...] | list[str] = (),
        pinned: bool = False,
        stability: float | None = None,
        merged_from: tuple[int, ...] | list[int] = (),
        source: str | None = None,
        now: datetime | None = None,
    ) -> Memory:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
        now = now or datetime.now()
        importance = st.clamp_importance(importance)
        pinned = pinned or importance >= st.PINNED_IMPORTANCE
        if stability is None:
            stability = st.initial_stability(importance, valence)
        if pinned:
            stability = st.INFINITE
        cur = self.conn.execute(
            "INSERT INTO memories (kind, text, created, source_episode, importance, valence, arousal,"
            " stability, last_recalled, recall_count, superseded_by, merged_from, tags, pinned, source)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, ?, ?)",
            (kind, text, iso(now), source_episode, importance, valence, arousal, stability,
             iso(now), json.dumps(list(merged_from)), json.dumps(list(tags), ensure_ascii=False),
             int(pinned), source),
        )
        self.conn.commit()
        return self.get(cur.lastrowid)

    def touch(self, memory_id: int, now: datetime | None = None) -> Memory:
        """She just used this memory: it gets stronger, more so if it was nearly gone."""
        now = now or datetime.now()
        m = self.get(memory_id)
        new_s = st.after_recall(m.stability, m.retrievability(now))
        self.conn.execute(
            "UPDATE memories SET stability = ?, last_recalled = ?, recall_count = recall_count + 1"
            " WHERE id = ?",
            (new_s, iso(now), memory_id),
        )
        self.conn.commit()
        return self.get(memory_id)

    def supersede(self, old_id: int, new_id: int) -> None:
        self.conn.execute("UPDATE memories SET superseded_by = ? WHERE id = ?", (new_id, old_id))
        self.conn.commit()

    def correct(
        self, old_id: int, text: str, *, importance: int | None = None,
        now: datetime | None = None,
    ) -> Memory:
        """He corrected her: a new memory replaces the old one, which stays as 'what she used to think'."""
        old = self.get(old_id)
        now = now or datetime.now()
        importance = old.importance if importance is None else importance
        fresh = st.initial_stability(importance, old.valence)
        stability = max(fresh, old.stability) if fresh != st.INFINITE else st.INFINITE
        new = self.add(
            old.kind, text, importance=importance, valence=old.valence, arousal=old.arousal,
            source_episode=old.source_episode, tags=old.tags, pinned=old.pinned,
            stability=stability, now=now,
        )
        self.supersede(old_id, new.id)
        return new

    def merge(self, ids: list[int], text: str, *, now: datetime | None = None) -> Memory:
        """Nightly: several near-duplicates become one, more stable, with its sources noted."""
        olds = [self.get(i) for i in ids]
        if not olds:
            raise ValueError("merge needs at least one memory")
        now = now or datetime.now()
        tags: list[str] = []
        for o in olds:
            tags += [t for t in o.tags if t not in tags]
        new = self.add(
            olds[0].kind, text,
            importance=max(o.importance for o in olds),
            valence=sum(o.valence for o in olds) / len(olds),
            arousal=max(o.arousal for o in olds),
            source_episode=olds[0].source_episode, tags=tags,
            pinned=any(o.pinned for o in olds),
            stability=st.after_merge(*(o.stability for o in olds)),
            merged_from=ids, now=now,
        )
        for o in olds:
            self.supersede(o.id, new.id)
        return new

    # --- read --------------------------------------------------------------

    def get(self, memory_id: int) -> Memory:
        row = self.conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if row is None:
            raise KeyError(f"no memory {memory_id}")
        return _from_row(row)

    def alive(self, kind: str | None = None) -> list[Memory]:
        sql = "SELECT * FROM memories WHERE superseded_by IS NULL"
        args: tuple = ()
        if kind:
            sql += " AND kind = ?"
            args = (kind,)
        return [_from_row(r) for r in self.conn.execute(sql + " ORDER BY id", args)]

    def profile(self, limit: int = PROFILE_SIZE) -> list[Memory]:
        """The facts she always keeps in mind: pinned first, then the most stable."""
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE superseded_by IS NULL AND kind = 'fact'"
            " AND (pinned = 1 OR importance >= ?)"
            " ORDER BY pinned DESC, stability DESC, importance DESC, id LIMIT ?",
            (PROFILE_IMPORTANCE, limit),
        )
        return [_from_row(r) for r in rows]

    def howto_card(self, limit: int = 8) -> list[Memory]:
        """How to get along with him: the rules she has drawn, always in mind (decision 11)."""
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE superseded_by IS NULL AND kind = 'howto'"
            " ORDER BY importance DESC, stability DESC, id DESC LIMIT ?", (limit,)
        )
        return [_from_row(r) for r in rows]

    def seen_recently(self, now: datetime, days: int = 7) -> list[Memory]:
        """World memories from the last `days`, newest first (also the URLs not to reopen)."""
        since = iso(now - timedelta(days=days))
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE kind = 'world' AND created >= ? ORDER BY id DESC", (since,)
        )
        return [_from_row(r) for r in rows]

    def former(self, memory_id: int) -> Memory | None:
        """The memory this one replaced, if any ('你之前说是周五来着')."""
        row = self.conn.execute(
            "SELECT * FROM memories WHERE superseded_by = ? ORDER BY id DESC LIMIT 1", (memory_id,)
        ).fetchone()
        return _from_row(row) if row else None

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

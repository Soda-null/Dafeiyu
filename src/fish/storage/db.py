"""Connection and schema. Tables: docs/memory_design_zh.md §9."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 14
# Columns added after a table first shipped; applied to older databases on connect.
ADDED_COLUMNS = [("memories", "source", "TEXT"),
                 ("memories", "times", "INTEGER NOT NULL DEFAULT 1"),  # decision 20: how often it happened
                 ("memories", "gist_due", "INTEGER NOT NULL DEFAULT 0"),  # 1: rewrite as a gist tonight
                 ("memories", "pattern", "TEXT"),  # its wording before the gist, to recognise the next time
                 ("memories", "about", "TEXT"),  # decision 21: 路过 / 日常 / 本人 / 一辈子 / 待印证
                 ("memories", "last_time", "TEXT"),  # the day it last happened: one count per day
                 ("memories", "why", "TEXT"),  # memory v3: why it was superseded (longterm.WHYS)
                 ("memories", "happened_on", "TEXT"),  # memory v3: YYYY-MM-DD the thing happened
                 ("memories", "pact", "TEXT"),  # memory v3: him / her / both, a promise or his nickname for her
                 ("memories", "pact_state", "TEXT"),  # memory v3: open / kept / dropped
                 ("memories", "outcome", "TEXT"),  # memory v3: how it turned out; the text stays as it was
                 ("prospective", "asked_episode", "INTEGER"),  # memory v3: the chat she asked it in
                 ("episodes", "keys", "TEXT"),  # memory v3: JSON list, the tags and names its notes carry
                 ("stickers", "digest", "TEXT")]  # sha1 of the picture: the same one is kept once

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY,
    ts          TEXT NOT NULL,            -- ISO 8601, local time
    role        TEXT NOT NULL,            -- 'user' | 'fish'
    text        TEXT NOT NULL,
    channel     TEXT NOT NULL,            -- 'terminal' | 'wechat'
    episode_id  INTEGER,                  -- episodes.id; NULL before episodes existed
    folded      INTEGER NOT NULL DEFAULT 0 -- 1 once summarized into the episode
);
CREATE TABLE IF NOT EXISTS episodes (
    id              INTEGER PRIMARY KEY,
    started         TEXT NOT NULL,
    last_active     TEXT NOT NULL,
    ended           TEXT,                 -- NULL while open
    channel         TEXT NOT NULL,
    running_summary TEXT,                 -- folded in during the chat
    summary         TEXT,                 -- written at close
    gist            TEXT,                 -- one line, written at close
    importance      INTEGER,
    valence         REAL,
    level           INTEGER NOT NULL DEFAULT 0  -- 0 full / 1 summary only / 2 gist only
);
CREATE TABLE IF NOT EXISTS memories (
    id            INTEGER PRIMARY KEY,
    kind          TEXT NOT NULL,          -- fact | event | howto | insight | self
    text          TEXT NOT NULL,
    created       TEXT NOT NULL,
    source_episode INTEGER,
    importance    INTEGER NOT NULL,       -- 1..10
    valence       REAL NOT NULL DEFAULT 0,
    arousal       REAL NOT NULL DEFAULT 0,
    stability     REAL NOT NULL,          -- days; Inf when pinned
    last_recalled TEXT NOT NULL,
    recall_count  INTEGER NOT NULL DEFAULT 0,
    superseded_by INTEGER,                -- memories.id; NULL = current
    merged_from   TEXT,                   -- JSON list of ids
    tags          TEXT,                   -- JSON list of keywords
    embedding     BLOB,                   -- version 2 recall
    pinned        INTEGER NOT NULL DEFAULT 0,
    source        TEXT                    -- kind=world: the URL she saw it at
);
CREATE TABLE IF NOT EXISTS prospective (
    id            INTEGER PRIMARY KEY,
    text          TEXT NOT NULL,
    due           TEXT NOT NULL,          -- YYYY-MM-DD
    created       TEXT NOT NULL,
    source_memory INTEGER,
    status        TEXT NOT NULL           -- open | asked | expired
);
CREATE TABLE IF NOT EXISTS diary (
    day   TEXT PRIMARY KEY,               -- YYYY-MM-DD
    text  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mood (
    key     TEXT PRIMARY KEY,             -- energy | boredom | hunger (closeness: relationship table)
    value   REAL NOT NULL,                -- 0..100
    updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS relationship (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL,
    updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS routine_runs (
    name     TEXT PRIMARY KEY,            -- nightly | reflect | browse
    last_run TEXT NOT NULL                -- YYYY-MM-DD
);
CREATE TABLE IF NOT EXISTS mood_log (          -- layer C, one row per turn (decision 13)
    id      INTEGER PRIMARY KEY,
    ts      TEXT NOT NULL,
    word    TEXT,                         -- the mood she reported this turn
    energy  REAL NOT NULL,
    boredom REAL NOT NULL,
    hunger  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS phase (             -- layer B, one row per fish day, with inertia
    day    TEXT PRIMARY KEY,
    tone   REAL NOT NULL,                 -- -1 low .. 1 good, moves slowly
    drive  REAL NOT NULL,                 -- 0 flat .. 1 keen, moves slowly
    focus  TEXT,                          -- JSON list: what she is into these days
    line   TEXT                           -- one sentence in her words
);
CREATE TABLE IF NOT EXISTS traits (            -- layer A, the base character's sliders
    key     TEXT PRIMARY KEY,
    value   REAL NOT NULL,                -- -1 .. 1
    updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS growth_notes (      -- layer A, her own monthly "how I changed"
    month   TEXT PRIMARY KEY,             -- YYYY-MM-DD of the review
    text    TEXT NOT NULL,
    changes TEXT                          -- JSON {trait: delta}
);
CREATE TABLE IF NOT EXISTS stickers (
    id        INTEGER PRIMARY KEY,
    file      TEXT NOT NULL,              -- under data/stickers/
    caption   TEXT NOT NULL,              -- her words for it
    tags      TEXT,                       -- JSON list
    created   TEXT NOT NULL,
    source    TEXT NOT NULL,              -- him | inbox
    uses      INTEGER NOT NULL DEFAULT 0,
    last_used TEXT
);
CREATE TABLE IF NOT EXISTS pastimes (          -- decision 24: what she follows (a book she reads)
    id        INTEGER PRIMARY KEY,
    kind      TEXT NOT NULL,              -- the activity's key, e.g. book
    title     TEXT NOT NULL,              -- what she calls it
    ref       TEXT NOT NULL,              -- the activity's own id (a Wikisource title)
    progress  TEXT NOT NULL DEFAULT '{}', -- JSON, the activity's own (chapter, offset)
    status    TEXT NOT NULL DEFAULT 'on', -- on | dropped | finished
    started   TEXT NOT NULL,
    touched   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leisure_log (       -- decision 24: one row per free moment
    id        INTEGER PRIMARY KEY,
    ts        TEXT NOT NULL,
    choice    TEXT,                       -- activity key, 'nothing', or NULL while asking
    line      TEXT,                       -- the menu line she picked
    why       TEXT,                       -- her one sentence
    result    TEXT,                       -- what came of it, one line
    memories  TEXT                        -- JSON list of memory ids written
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open (and create) the database; parent folder is created too."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table, column, decl in ADDED_COLUMNS:
        present = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in present:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()

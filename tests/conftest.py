"""Tests open hundreds of throwaway databases. Skip waiting for the disk on every commit:
on Windows that wait made the suite take 13 minutes instead of seconds. Only tests load this
file; her real database keeps SQLite's safe default."""

import sqlite3

_connect = sqlite3.connect


def _connect_without_fsync(*args, **kwargs):
    conn = _connect(*args, **kwargs)
    conn.execute("PRAGMA synchronous = OFF")
    return conn


sqlite3.connect = _connect_without_fsync

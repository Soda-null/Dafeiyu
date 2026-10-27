"""SQLite storage: one file holds everything the fish remembers."""

from fish.storage.db import connect, init_schema

__all__ = ["connect", "init_schema"]

"""Her sticker album (decision 12): pictures she kept because they made her laugh, each with
a caption in her words, so she can pick one to send. Files live under data/stickers/."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fish.memory.longterm import iso

EXT = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}


@dataclass(frozen=True)
class Sticker:
    id: int
    path: Path
    caption: str
    tags: tuple[str, ...]
    created: str
    source: str  # 'him' | 'inbox'
    uses: int


def _from_row(r: sqlite3.Row, folder: Path) -> Sticker:
    return Sticker(r["id"], folder / r["file"], r["caption"], tuple(json.loads(r["tags"] or "[]")),
                   r["created"], r["source"], r["uses"])


class StickerAlbum:
    def __init__(self, conn: sqlite3.Connection, folder: Path) -> None:
        self.conn = conn
        self.folder = folder

    def add(self, data: bytes, mime: str, caption: str, *, tags=(), source: str = "him",
            now: datetime | None = None) -> Sticker:
        now = now or datetime.now()
        self.folder.mkdir(parents=True, exist_ok=True)
        cur = self.conn.execute(
            "INSERT INTO stickers (file, caption, tags, created, source, uses) VALUES ('', ?, ?, ?, ?, 0)",
            (caption[:80], json.dumps([str(t) for t in tags], ensure_ascii=False), iso(now), source),
        )
        sid = cur.lastrowid
        name = f"{sid}.{EXT.get(mime, 'jpg')}"
        (self.folder / name).write_bytes(data)
        self.conn.execute("UPDATE stickers SET file = ? WHERE id = ?", (name, sid))
        self.conn.commit()
        return self.get(sid)

    def get(self, sticker_id: int) -> Sticker:
        row = self.conn.execute("SELECT * FROM stickers WHERE id = ?", (sticker_id,)).fetchone()
        if row is None:
            raise KeyError(f"no sticker {sticker_id}")
        return _from_row(row, self.folder)

    def all(self, limit: int = 30) -> list[Sticker]:
        rows = self.conn.execute("SELECT * FROM stickers ORDER BY uses DESC, id DESC LIMIT ?", (limit,))
        return [_from_row(r, self.folder) for r in rows]

    def touch(self, sticker_id: int, now: datetime | None = None) -> None:
        self.conn.execute("UPDATE stickers SET uses = uses + 1, last_used = ? WHERE id = ?",
                          (iso(now or datetime.now()), sticker_id))
        self.conn.commit()

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM stickers").fetchone()[0]

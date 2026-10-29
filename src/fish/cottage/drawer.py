"""Her bedside drawer (decision 39): a letter to him each night, never sent. Nothing shows it;
opening it in plain words does, and leaves a trace she notices."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

DRAWER = "抽屉"  # next to the room's file, so data/cottage/抽屉/ for real and a temp folder in tests
PEEKED = "床头的抽屉被人翻过，信的顺序乱了"  # what a look into it leaves: she can tell
LETTERS_SHOWN = 7


class DrawerMixin:
    """Part of Cottage (room.py): her drawer. Uses the room's path / load / save / note."""

    @property
    def drawer(self) -> Path:
        return self.path.parent / DRAWER

    def put_letter(self, day: date, text: str) -> Path:
        """Tonight's letter into her drawer; a night written twice keeps the later one."""
        self.drawer.mkdir(parents=True, exist_ok=True)
        path = self.drawer / f"{day.isoformat()}.md"
        path.write_text(f"# {day.isoformat()}\n\n{text.strip()}\n", encoding="utf-8")
        return path

    def letter(self, day: date) -> str:
        path = self.drawer / f"{day.isoformat()}.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").split("\n", 2)[-1].strip()

    def open_drawer(self, now: datetime, n: int = LETTERS_SHOWN) -> list[tuple[str, str]]:
        """Someone looks into her drawer: her letters, newest first; and the room keeps a trace
        she will notice."""
        room = self.load(now)
        self.note(room, now, PEEKED)
        self.save(room)
        paths = sorted(self.drawer.glob("*.md"), reverse=True)[:n] if self.drawer.is_dir() else []
        return [(p.stem, p.read_text(encoding="utf-8").split("\n", 2)[-1].strip()) for p in paths]

    def peeked(self, start: datetime, end: datetime) -> list[str]:
        """When her drawer was looked into, between two moments ("12:30")."""
        room = self.load(end)
        return [e["ts"][11:16] for e in room.events
                if e["line"] == PEEKED and start <= datetime.fromisoformat(e["ts"]) < end]

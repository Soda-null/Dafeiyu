"""Layer A of her character (decision 13): the base, which drifts on its own, slowly, inside
bounds nobody can push past.

The persona file is her origin and is never rewritten. On top of it sit five sliders
(-1..1) that start where the file puts her. About once a month she looks back at how she
has been and may move each slider by at most MAX_STEP; the sliders can never leave [-1, 1]
and the parts of the file marked as bottom lines are not sliders at all. So she changes the
way people do — a notch a month, in character — and cannot be talked out of who she is.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from fish.memory.longterm import iso

MAX_STEP = 0.15
NOTICEABLE = 0.2  # how far from the origin before the prompt mentions it

# key: (origin value, what -1 means, what +1 means)
TRAITS: dict[str, tuple[float, str, str]] = {
    "guard": (-0.3, "防备", "敞开"),
    "talk": (-0.4, "话少", "话多"),
    "tease": (0.2, "温和", "嘴毒"),
    "cling": (-0.2, "独立", "黏人"),
    "outlook": (0.0, "丧", "乐观"),
}


@dataclass(frozen=True)
class Growth:
    month: str
    text: str
    changes: dict[str, float]


class TraitStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def values(self) -> dict[str, float]:
        stored = {r["key"]: r["value"] for r in self.conn.execute("SELECT key, value FROM traits")}
        return {k: stored.get(k, origin) for k, (origin, _, _) in TRAITS.items()}

    def apply(self, changes: dict[str, float], now: datetime | None = None) -> dict[str, float]:
        """Move sliders by the requested amounts, each clipped to MAX_STEP and the bounds."""
        current = self.values()
        applied: dict[str, float] = {}
        for key, delta in changes.items():
            if key not in TRAITS:
                continue
            try:
                delta = max(-MAX_STEP, min(MAX_STEP, float(delta)))
            except (TypeError, ValueError):
                continue
            new = max(-1.0, min(1.0, current[key] + delta))
            if abs(new - current[key]) < 1e-9:
                continue
            self.conn.execute("INSERT OR REPLACE INTO traits (key, value, updated) VALUES (?, ?, ?)",
                              (key, new, iso(now or datetime.now())))
            applied[key] = round(new - current[key], 3)
        self.conn.commit()
        return applied

    def describe(self) -> list[str]:
        """Sentences for the prompt, only for sliders that have moved noticeably from the origin."""
        out = []
        for key, value in self.values().items():
            origin, low, high = TRAITS[key]
            if value - origin >= NOTICEABLE:
                out.append(f"比刚认识时{high}了些")
            elif origin - value >= NOTICEABLE:
                out.append(f"比刚认识时{low}了些")
        return out

    def describe_all(self) -> list[str]:
        """Every slider as "低端 … 高端：位置", for her own monthly review."""
        out = []
        for key, value in self.values().items():
            _, low, high = TRAITS[key]
            pos = "偏" + high if value > 0.2 else "偏" + low if value < -0.2 else "中间"
            out.append(f"{key}（{low}↔{high}）：{pos}")
        return out

    # --- growth notes -----------------------------------------------------------

    def add_growth(self, month: str, text: str, changes: dict[str, float]) -> None:
        self.conn.execute("INSERT OR REPLACE INTO growth_notes (month, text, changes) VALUES (?, ?, ?)",
                          (month, text, json.dumps(changes, ensure_ascii=False)))
        self.conn.commit()

    def growth_notes(self, limit: int = 3) -> list[Growth]:
        rows = self.conn.execute("SELECT * FROM growth_notes ORDER BY month DESC LIMIT ?", (limit,))
        return [Growth(r["month"], r["text"], json.loads(r["changes"] or "{}")) for r in rows]

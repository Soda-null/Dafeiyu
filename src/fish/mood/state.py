"""Layer C of her character (decision 13): how she feels right now.

Three numbers 0..100 — energy, boredom, hunger — move every turn and with the clock. They
reset each night to a baseline that layer B (the phase) sets, so a flat week starts her days
tired and a good one keen. Closeness is not here: it is the relationship's, and moves over
days (memory/relationship.py).
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, replace
from datetime import datetime

from fish.config import owner_words
from fish.memory.longterm import iso

KEYS = ("energy", "boredom", "hunger")
DEFAULTS = {"energy": 70.0, "boredom": 20.0, "hunger": 40.0}
FOOD_WORDS = ("吃", "饭", "喂", "零食", "夜宵")
FOOD_TALK_WITH_KITCHEN = 3  # decision 26: talking about food is not eating
# What each reported mood word says about her tone that turn, -1..1 (layer B reads these).
WORD_TONE = {"开心": 1.0, "好奇": 0.5, "平静": 0.1, "无聊": -0.3, "困": -0.2, "饿": -0.2,
             "烦": -0.7, "难过": -1.0}
# Closeness stages (decision 11); the names match the headings in docs/persona_zh.md.
STAGES = ((60.0, "很熟"), (25.0, "熟了"), (0.0, "刚认识"))


def stage_of(closeness: float) -> str:
    for threshold, name in STAGES:
        if closeness >= threshold:
            return name
    return STAGES[-1][1]


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


@dataclass
class Mood:
    energy: float
    boredom: float
    hunger: float

    def describe(self, stage: str | None = None) -> str:
        """One plain Chinese sentence for the prompt; numbers never reach the model."""
        parts = []
        if self.energy < 30:
            parts.append("很困，不太想打字")
        elif self.energy > 75:
            parts.append("挺精神")
        if self.hunger > 70:
            parts.append("饿了，满脑子白饭")
        if self.boredom > 60:
            parts.append("有点无聊，想换个话题")
        if stage:
            parts.append(owner_words({"刚认识": "和他刚认识", "熟了": "和他熟了", "很熟": "和他很熟了"}[stage]))
        return "，".join(parts) if parts else "状态一般"


class MoodStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def load(self) -> Mood:
        rows = self.conn.execute("SELECT key, value FROM mood").fetchall()
        values = dict(DEFAULTS)
        values.update({r["key"]: r["value"] for r in rows if r["key"] in KEYS})
        return Mood(**{k: values[k] for k in KEYS})

    def save(self, mood: Mood) -> None:
        now = iso(datetime.now())
        for k, v in asdict(mood).items():
            self.conn.execute(
                "INSERT OR REPLACE INTO mood (key, value, updated) VALUES (?, ?, ?)",
                (k, _clamp(v), now),
            )
        self.conn.commit()

    @staticmethod
    def apply_clock(mood: Mood, now: datetime | None = None) -> Mood:
        """How she feels right now: the stored baseline plus the time of day.
        Returns a copy; the offset is never saved."""
        hour = (now or datetime.now()).hour
        shown = replace(mood)
        if 0 <= hour < 6:
            shown.energy = _clamp(mood.energy - 45)
        elif 9 <= hour < 12:
            shown.energy = _clamp(mood.energy + 10)
        if hour in (11, 12, 17, 18):
            shown.hunger = _clamp(mood.hunger + 20)
        return shown

    @staticmethod
    def after_turn(mood: Mood, user_text: str, fish_text: str, *, reported: str | None = None,
                   topic: str | None = None, last_topic: str | None = None, kitchen: bool = False) -> Mood:
        """How one exchange moves her: the mood she reported, whether the topic repeats,
        and whether he brought up food. With a kitchen (decision 26) only eating feeds her;
        talk of food makes her hungrier."""
        mood.energy = _clamp(mood.energy - 1)
        mood.hunger = _clamp(mood.hunger + 2)  # time passes; food words below undo it
        if topic and last_topic and topic == last_topic:
            mood.boredom = _clamp(mood.boredom + 8)
        else:
            mood.boredom = _clamp(mood.boredom - 6)
        if reported == "无聊":
            mood.boredom = _clamp(mood.boredom + 10)
        elif reported in ("开心", "好奇"):
            mood.boredom = _clamp(mood.boredom - 8)
        if any(k in user_text for k in FOOD_WORDS):
            mood.hunger = _clamp(mood.hunger + (FOOD_TALK_WITH_KITCHEN if kitchen else -20))
        return mood

    def log(self, mood: Mood, word: str | None, now: datetime | None = None) -> None:
        """One row per turn, so the night can read the day's tone."""
        self.conn.execute(
            "INSERT INTO mood_log (ts, word, energy, boredom, hunger) VALUES (?, ?, ?, ?, ?)",
            (iso(now or datetime.now()), word, mood.energy, mood.boredom, mood.hunger),
        )
        self.conn.commit()

    def day_tone(self, start: datetime, end: datetime) -> tuple[float | None, float | None]:
        """(mean tone of the words she reported, mean energy) between start and end, or Nones."""
        rows = self.conn.execute(
            "SELECT word, energy FROM mood_log WHERE ts >= ? AND ts < ?", (iso(start), iso(end))
        ).fetchall()
        if not rows:
            return None, None
        tones = [WORD_TONE[r["word"]] for r in rows if r["word"] in WORD_TONE]
        tone = sum(tones) / len(tones) if tones else None
        return tone, sum(r["energy"] for r in rows) / len(rows)

    def rest(self, tone: float = 0.0, drive: float = 0.6) -> Mood:
        """Nightly: sleep. Where she wakes up depends on the phase (layer B): a keen stretch
        gives a brighter morning, a low one a duller one. She wakes a bit hungry."""
        mood = self.load()
        mood.energy = _clamp(30 + 60 * drive)
        mood.boredom = _clamp(DEFAULTS["boredom"] - 10 * tone)
        mood.hunger = _clamp(mood.hunger + 10)
        self.save(mood)
        return mood

"""Urges to text him (decisions 10, 26, 30): something she saw today worth sharing, a
follow-up that came due, a long silence, an anniversary, plain boredom, something that
happened at home. Moved here from brain/reach.py unchanged (decision 46); in this order she
is told them."""

from __future__ import annotations

from fish.config import owner_words
from fish.memory import DUE_SHOWN, MemoryStore, ProspectiveStore, Relationship, last_his_message
from fish.urges.rules import (ANNIVERSARIES, BORED_LEVEL, BORED_SILENCE_HOURS, SHARE_AT_MOST, SHARE_IMPORTANCE,
                              SILENCE_HOURS)
from fish.urges.urge import HIM, Scene, Urge


def silence_hours(s: Scene) -> float:
    his = last_his_message(s.conn)
    return (s.now - his).total_seconds() / 3600 if his else 0.0


def seen(s: Scene) -> list[Urge]:
    found = [m for m in MemoryStore(s.conn).seen_recently(s.now, 1)
             if m.importance >= SHARE_IMPORTANCE and m.id not in s.shared][:SHARE_AT_MOST]
    return [Urge(HIM, "seen", f"今天看到的（见闻 #{m.id}）：{m.text}", ref=m) for m in found]


def due(s: Scene) -> list[Urge]:
    return [Urge(HIM, "due", f"惦记的事到日子了（惦记 #{f.id}）：{f.text}", ref=f)
            for f in ProspectiveStore(s.conn).due(s.now)[:DUE_SHOWN]]


def silence(s: Scene) -> list[Urge]:
    hours = silence_hours(s)
    return [Urge(HIM, "silence", owner_words(f"他有 {int(hours)} 个小时没来找你了"), ref=hours)] if hours >= SILENCE_HOURS else []


def anniversary(s: Scene) -> list[Urge]:
    known = Relationship(s.conn).days_known(s.now)
    if known in ANNIVERSARIES or (known > 0 and known % 100 == 0):
        return [Urge(HIM, "anniversary", f"今天是你们认识的第 {known} 天", ref=known)]
    return []


def bored(s: Scene) -> list[Urge]:
    return [Urge(HIM, "bored", "你有点无聊")] if s.mood.boredom >= BORED_LEVEL and silence_hours(s) >= BORED_SILENCE_HOURS else []


def home(s: Scene) -> list[Urge]:
    return [Urge(HIM, "home", f"家里的事：{line}", ref=line) for line in s.home]


SOURCES = (seen, due, silence, anniversary, bored, home)


def about_him(s: Scene) -> list[Urge]:
    """Every urge to text him right now, in the order she is told them."""
    return [u for source in SOURCES for u in source(s)]

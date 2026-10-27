"""She speaks first (decision 10).

Two layers. The rules gate costs nothing and runs every poll: on, daytime, at most
MAX_PER_DAY a day, hours apart, not right after he wrote, not re-asked within hours of a
"no". Then a trigger must exist: something she saw today worth sharing, a follow-up that
came due, a long silence, an anniversary, or plain boredom. Only then is the model asked
once whether she feels like saying something, and what. Not saying anything is her call.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from fish.brain.ask import ask_json
from fish.brain.llm import LLM
from fish.brain.prompt import WEEKDAYS
from fish.config import owner_words
from fish.memory import Followup, Memory, MemoryStore, ProspectiveStore, Relationship, Window
from fish.memory.longterm import iso
from fish.memory.prospective import DUE_SHOWN
from fish.mood import Mood

DAY_START, DAY_END = time(9, 0), time(22, 30)
MIN_GAP = timedelta(hours=6)
AFTER_HIS_MESSAGE = timedelta(minutes=60)
RECONSIDER_AFTER = timedelta(hours=3)
SILENCE_TRIGGER_HOURS = 18
# WeChat drops bot messages to someone silent for 24 h without telling us (community docs),
# so after this long she cannot reach him and waits.
WINDOW_HOURS = 23
BORED_LEVEL, BORED_SILENCE_HOURS = 60, 6
SHARE_IMPORTANCE = 4
ANNIVERSARIES = (7, 30, 100, 365, 730)


@dataclass
class Triggers:
    seen: list[Memory] = field(default_factory=list)
    due: list[Followup] = field(default_factory=list)
    silence_hours: float = 0.0
    anniversary: int | None = None
    bored: bool = False

    @property
    def any(self) -> bool:
        return bool(self.seen or self.due or self.silence_hours >= SILENCE_TRIGGER_HOURS
                    or self.anniversary or self.bored)


@dataclass(frozen=True)
class ReachOut:
    text: str
    asked: tuple[int, ...] = ()
    shared: tuple[int, ...] = ()


class ReachPolicy:
    """The rules, with their little state kept in the relationship ledger (reach_* keys)."""

    def __init__(self, conn: sqlite3.Connection, *, enabled: bool = True, max_per_day: int = 2) -> None:
        self.conn = conn
        self.enabled = enabled
        self.max_per_day = max_per_day
        self.kv = Relationship(conn)

    # --- state -----------------------------------------------------------------

    def _dt(self, key: str) -> datetime | None:
        v = self.kv.get(key)
        return datetime.fromisoformat(v) if v else None

    def count_today(self, now: datetime) -> int:
        return int(self.kv.get("reach_count", "0") or 0) if self.kv.get("reach_day") == now.date().isoformat() else 0

    def shared_ids(self) -> set[int]:
        return set(json.loads(self.kv.get("reach_shared", "[]") or "[]"))

    def record_considered(self, now: datetime) -> None:
        self.kv.set("reach_last_considered", iso(now), now)

    def record_sent(self, now: datetime, ro: ReachOut) -> None:
        day = now.date().isoformat()
        count = self.count_today(now) + 1
        self.kv.set("reach_day", day, now)
        self.kv.set("reach_count", str(count), now)
        self.kv.set("reach_last_sent", iso(now), now)
        if ro.shared:
            self.kv.set("reach_shared", json.dumps(sorted(self.shared_ids() | set(ro.shared))), now)

    def last_his_message(self) -> datetime | None:
        row = self.conn.execute("SELECT MAX(ts) FROM messages WHERE role = 'user'").fetchone()
        return datetime.fromisoformat(row[0]) if row and row[0] else None

    # --- the gate --------------------------------------------------------------

    def refused(self, now: datetime) -> str | None:
        """Why she may not reach out right now, or None when the gate is open."""
        if not self.enabled:
            return "off"
        if not DAY_START <= now.time() <= DAY_END:
            return "night"
        if self.count_today(now) >= self.max_per_day:
            return "enough today"
        last_sent = self._dt("reach_last_sent")
        if last_sent and now - last_sent < MIN_GAP:
            return "too soon"
        his = self.last_his_message()
        if his is None:
            return "never met"
        if now - his < AFTER_HIS_MESSAGE:
            return "just talked"
        if now - his > timedelta(hours=WINDOW_HOURS):
            return "out of reach"
        considered = self._dt("reach_last_considered")
        if considered and now - considered < RECONSIDER_AFTER:
            return "decided recently"
        return None

    def triggers(self, now: datetime, mood: Mood) -> Triggers:
        store = MemoryStore(self.conn)
        his = self.last_his_message()
        silence = (now - his).total_seconds() / 3600 if his else 0.0
        shared = self.shared_ids()
        seen = [m for m in store.seen_recently(now, 1)
                if m.importance >= SHARE_IMPORTANCE and m.id not in shared][:3]
        due = ProspectiveStore(self.conn).due(now)[:DUE_SHOWN]
        known = self.kv.days_known(now)
        anniversary = known if known in ANNIVERSARIES or (known > 0 and known % 100 == 0) else None
        bored = mood.boredom >= BORED_LEVEL and silence >= BORED_SILENCE_HOURS
        return Triggers(seen, due, silence, anniversary, bored)


class Reacher:
    """Asks her, once, whether she wants to say something."""

    def __init__(self, llm: LLM, persona: str) -> None:
        self.llm = llm
        self.persona = persona

    def decide(self, now: datetime, mood: Mood, trig: Triggers, recent: list[str]) -> ReachOut | None:
        reasons: list[str] = []
        for m in trig.seen:
            reasons.append(f"- 今天看到的（见闻 #{m.id}）：{m.text}")
        for f in trig.due:
            reasons.append(f"- 惦记的事到日子了（惦记 #{f.id}）：{f.text}")
        if trig.silence_hours >= SILENCE_TRIGGER_HOURS:
            reasons.append(owner_words(f"- 他有 {int(trig.silence_hours)} 个小时没来找你了"))
        if trig.anniversary:
            reasons.append(f"- 今天是你们认识的第 {trig.anniversary} 天")
        if trig.bored:
            reasons.append("- 你有点无聊")
        if trig.silence_hours >= 1:
            since = owner_words(f"他上次找你是 {int(trig.silence_hours)} 小时前。")
        else:
            since = "你们刚聊过。"
        when = f"{now.strftime('%Y-%m-%d')} 周{WEEKDAYS[now.weekday()]} {now.strftime('%H:%M')}"
        data = ask_json(self.llm, "reach_out", persona=self.persona, now=when, since=since,
                        mood=mood.describe(), reasons="\n".join(reasons) or "（没什么特别的）",
                        recent="\n".join(f"- {r}" for r in recent) or "（还没聊过）", temperature=1.0)
        if not data:
            return None
        say = str(data.get("say") or "").strip()
        if not say:
            return None
        ok_asked = {f.id for f in trig.due}
        ok_shared = {m.id for m in trig.seen}
        asked = tuple(i for i in (data.get("asked") or []) if isinstance(i, int) and i in ok_asked)
        shared = tuple(i for i in (data.get("shared") or []) if isinstance(i, int) and i in ok_shared)
        return ReachOut(say[:300], asked, shared)


def recent_lines(window: Window, n: int = 6) -> list[str]:
    turns = window.recent()[-n:]
    who = owner_words("他")
    return [f"{who if t.role == 'user' else '你'}：{t.text}" for t in turns]

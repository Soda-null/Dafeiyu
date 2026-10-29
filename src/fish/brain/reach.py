"""She speaks first (decision 10).

Two layers. The gate costs nothing and runs every poll. It holds only what is not hers to
decide: she is on, awake, has met him, and WeChat would still deliver (decision 14). Beyond
that it only paces how often the thought crosses her mind: a random 20–60 minutes after she
last thought of it, or after he last wrote, so a running chat is not cut into. No gaps between
messages and no daily cap unless FISH_REACH_MAX sets one (decisions 30, 31).

Then a trigger must exist: something she saw today worth sharing, a follow-up that came due,
a long silence, an anniversary, something that happened at home (decision 26), or plain
boredom. Only then is the model asked once whether she feels like saying something, and
what. She is told how long ago he wrote and how many of her messages are still unanswered;
whether to say anything, and how often, is her call.
"""

from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from fish.brain.ask import ask_json
from fish.brain.checker import check_home
from fish.bus import Bus
from fish.brain.llm import LLM
from fish.brain.parse import clean_say, texting
from fish.brain.prompt import WEEKDAYS
from fish.config import Settings, owner_words
from fish.cottage import RoomNode, asleep_hours
from fish.memory import (DUE_SHOWN, Followup, Memory, MemoryStore, ProspectiveStore, Relationship, Window, iso,
                         last_his_message)
from fish.mood import Mood, MoodStore
from fish.msgs import SheSaid, TimePassed

THINK_PAUSE_MINUTES = (20, 60)  # how long until the thought "should I text him" comes back
HOME_LATELY = timedelta(hours=1)  # cottage events still fresh enough to mention
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
    home: list[str] = field(default_factory=list)  # what happened in her cottage lately
    unanswered: int = 0  # her own first messages since he last wrote
    last_sent_hours: float | None = None  # how long ago she last texted first

    @property
    def any(self) -> bool:
        return bool(self.seen or self.due or self.silence_hours >= SILENCE_TRIGGER_HOURS
                    or self.anniversary or self.bored or self.home)


@dataclass(frozen=True)
class ReachOut:
    text: str
    asked: tuple[int, ...] = ()
    shared: tuple[int, ...] = ()


class ReachPolicy:
    """The rules, with their little state kept in the relationship ledger (reach_* keys)."""

    def __init__(self, conn: sqlite3.Connection, *, enabled: bool = True, max_per_day: int = 0,
                 rng: random.Random | None = None) -> None:
        """max_per_day 0 means no cap: whether to send is hers (decision 30)."""
        self.conn = conn
        self.enabled = enabled
        self.max_per_day = max_per_day
        self.rng = rng or random.Random()
        self.kv = Relationship(conn)

    # --- state -----------------------------------------------------------------

    def _dt(self, key: str) -> datetime | None:
        v = self.kv.get(key)
        return datetime.fromisoformat(v) if v else None

    def count_today(self, now: datetime) -> int:
        return int(self.kv.get("reach_count", "0") or 0) if self.kv.get("reach_day") == now.date().isoformat() else 0

    def shared_ids(self) -> set[int]:
        return set(json.loads(self.kv.get("reach_shared", "[]") or "[]"))

    def _plan_next_think(self, base: datetime) -> datetime:
        at = base + timedelta(minutes=self.rng.uniform(*THINK_PAUSE_MINUTES))
        self.kv.set("reach_next_think", iso(at), base)
        self.kv.set("reach_think_base", iso(base), base)
        return at

    def next_think(self) -> datetime | None:
        """When the thought may come back. A message from him since it was planned moves it to
        a while after his message: while they are chatting she does not start something new."""
        his, base = self.last_his_message(), self._dt("reach_think_base")
        if his is not None and (base is None or his > base):
            return self._plan_next_think(his)
        return self._dt("reach_next_think")

    def record_considered(self, now: datetime) -> None:
        self.kv.set("reach_last_considered", iso(now), now)
        self._plan_next_think(now)

    def unanswered(self) -> int:
        """How many of her first messages are still waiting for his reply."""
        last_sent, his = self._dt("reach_last_sent"), self.last_his_message()
        if last_sent is None or (his is not None and his > last_sent):
            return 0
        return int(self.kv.get("reach_unanswered", "0") or 0)

    def record_sent(self, now: datetime, ro: ReachOut) -> None:
        day = now.date().isoformat()
        count = self.count_today(now) + 1
        self.kv.set("reach_unanswered", str(self.unanswered() + 1), now)
        self.kv.set("reach_day", day, now)
        self.kv.set("reach_count", str(count), now)
        self.kv.set("reach_last_sent", iso(now), now)
        if ro.shared:
            self.kv.set("reach_shared", json.dumps(sorted(self.shared_ids() | set(ro.shared))), now)

    def last_his_message(self) -> datetime | None:
        return last_his_message(self.conn)

    # --- the gate --------------------------------------------------------------

    def refused(self, now: datetime) -> str | None:
        """Why she may not reach out right now, or None when the gate is open."""
        if not self.enabled:
            return "off"
        if asleep_hours(now):
            return "asleep"
        if self.max_per_day and self.count_today(now) >= self.max_per_day:
            return "enough today"
        his = self.last_his_message()
        if his is None:
            return "never met"
        if now - his > timedelta(hours=WINDOW_HOURS):
            return "out of reach"
        nxt = self.next_think()
        if nxt is not None and now < nxt:
            return "not yet"
        return None

    def triggers(self, now: datetime, mood: Mood, home: list[str] | None = None) -> Triggers:
        """home: lines from her cottage's record for the last few hours, when she has one."""
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
        last_sent = self._dt("reach_last_sent")
        return Triggers(seen, due, silence, anniversary, bored, list(home or []), self.unanswered(),
                        (now - last_sent).total_seconds() / 3600 if last_sent else None)


class Reacher:
    """Asks her, once, whether she wants to say something."""

    def __init__(self, llm: LLM, persona: str) -> None:
        self.llm = llm
        self.persona = persona

    def decide(self, now: datetime, mood: Mood, trig: Triggers, recent: list[str], room: str = "") -> ReachOut | None:
        """room: her room as it is now (10-29: with only "他在窗台上放了一本《雪国》" to go by she
        texted "冰箱里那本《雪国》是你放的吧")."""
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
        for line in trig.home:
            reasons.append(f"- 家里的事：{line}")
        since = owner_words(f"他上次找你是{ago(trig.silence_hours)}。")
        if trig.unanswered and trig.last_sent_hours is not None:
            since += owner_words(f"你前面主动发的 {trig.unanswered} 条他还没回，最近一条是{ago(trig.last_sent_hours)}发的。")
        when = f"{now.strftime('%Y-%m-%d')} 周{WEEKDAYS[now.weekday()]} {now.strftime('%H:%M')}"
        data = ask_json(self.llm, "reach_out", persona=self.persona, now=when, since=since,
                        mood=mood.describe(), reasons="\n".join(reasons) or "（没什么特别的）",
                        recent="\n".join(f"- {r}" for r in recent) or "（还没聊过）",
                        room=room or "（没有）", temperature=1.0)
        if not data:
            return None
        say = texting(clean_say(str(data.get("say") or "")))
        if not say:
            return None
        ok_asked = {f.id for f in trig.due}
        ok_shared = {m.id for m in trig.seen}
        asked = tuple(i for i in (data.get("asked") or []) if isinstance(i, int) and i in ok_asked)
        shared = tuple(i for i in (data.get("shared") or []) if isinstance(i, int) and i in ok_shared)
        return ReachOut(say[:300], asked, shared)


def ago(hours: float) -> str:
    """" 40 分钟前" / " 3 小时前": plain words for the prompt."""
    return f" {int(hours * 60)} 分钟前" if hours < 1 else f" {int(hours)} 小时前"


class ReachNode:
    """Speaking first as a node (docs/nodes_design_zh.md step 3). Every tick she may think of
    him; when she says something and it goes through, the line goes out on the bus for whoever
    keeps the chat, and the gate's own ledger notes it. It does not know who listens."""

    def __init__(self, bus: Bus, conn: sqlite3.Connection, settings: Settings, *, llm: Callable[[], LLM],
                 persona: str, window: Window, room: RoomNode | None, say: Callable[[str], bool],
                 channel: Callable[[], str], fixed: Callable[[dict], None] | None = None) -> None:
        self.bus = bus
        self.conn = conn
        self.enabled, self.max_per_day = settings.reach_out, settings.reach_max_per_day
        self.llm = llm  # read each time: tests swap the model after building
        self.persona = persona
        self.window = window
        self.room = room  # her cottage, asked what happened lately, what she sees, its whole record; None when off
        self.say = say  # the channel's send for this tick; True when it went through
        self.channel = channel
        self.fixed = fixed  # told when the checker mended a line

    def consider(self, now: datetime) -> ReachOut | None:
        """Whether she wants to say something right now. Cheap unless the gate opens."""
        policy = ReachPolicy(self.conn, enabled=self.enabled, max_per_day=self.max_per_day)
        if policy.refused(now) is not None:
            return None
        mood = MoodStore.apply_clock(MoodStore(self.conn).load(), now, kitchen=self.room is not None)
        trig = policy.triggers(now, mood, home=self.room.lately(now, HOME_LATELY) if self.room is not None else [])
        if not trig.any:
            return None
        policy.record_considered(now)  # before asking, so a crash cannot loop on the model
        room = self.room.view(now, mood.hunger) if self.room is not None else ""
        ro = Reacher(self.llm(), self.persona).decide(now, mood, trig, recent_lines(self.window), room)
        if ro is None or self.room is None:
            return ro
        said, why = check_home(self.llm(), self.room.record(now), "", ro.text)
        if not why:
            return ro
        if self.fixed is not None:
            self.fixed({"at": now.isoformat(timespec="minutes"), "why": why, "said": said, "first": True})
        return ReachOut(said, ro.asked, ro.shared)

    def on_time(self, m: TimePassed) -> None:
        ro = self.consider(m.now)
        if ro is None or not self.say(ro.text):
            return
        self.bus.publish(SheSaid(ro.text, m.now, self.channel(), first=True, asked=ro.asked))
        ReachPolicy(self.conn).record_sent(m.now, ro)


def recent_lines(window: Window, n: int = 6) -> list[str]:
    turns = window.recent()[-n:]
    who = owner_words("他")
    return [f"{who if t.role == 'user' else '你'}：{t.text}" for t in turns]

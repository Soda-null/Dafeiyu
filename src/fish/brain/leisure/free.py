"""One free moment (decision 24): the gate, the menu, her pick, what she thought of it.

The gate costs nothing. When it opens, the activities lay out what she could do, shuffled,
with "nothing" as one line among the others; she is asked once. Nothing: the log gets a
line and that is all. Anything else: the activity fetches it and she is asked a second time
to write what she thought, as 见闻 (and at most one new life thread a day). Never notes
about him: this text came from the web, not from him (decision 9).
"""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Callable

from fish.brain.ask import ask_json
from fish.brain.leisure.base import Activity, Choice, Kit, Material
from fish.brain.leisure.cottage import KEY as COTTAGE_KEY
from fish.cottage import invented_act, layout
from fish.brain.prompt import WEEKDAYS
from fish.brain.world import Browser
from fish.memory import MemoryStore, Moment, Pastimes, last_his_message
from fish.mood import MoodStore
from fish.msgs import MoodMoved, SheSaid, TimePassed
from fish.world import Fetch, Searcher, load_sources, urllib_fetch

if TYPE_CHECKING:
    from fish.brain.respond import Brain

DAY_START, DAY_END = time(9, 0), time(23, 0)
AFTER_HIS_MESSAGE = timedelta(minutes=30)
MIN_GAP = timedelta(hours=3)
NOTHING = Choice("nothing", "什么都不干（发呆、打盹、数米粒）")
NOTHING_AT_HOME = Choice("nothing", "什么都不干（发呆、躺一会儿、看看湖）")  # with her cottage (decision 26)
SELF_NOTES_PER_DAY = 1  # decision 19: her life threads grow slowly
BOREDOM_AFTER_DOING, ENERGY_AFTER_NOTHING = -15, 5


class LeisurePolicy:
    """Is she free right now? Its state is the leisure_log itself."""

    def __init__(self, conn: sqlite3.Connection, *, enabled: bool = True, max_per_day: int = 3) -> None:
        self.conn = conn
        self.enabled = enabled
        self.max_per_day = max_per_day

    def refused(self, now: datetime) -> str | None:
        if not self.enabled:
            return "off"
        if not DAY_START <= now.time() <= DAY_END:
            return "night"
        today = datetime.combine(now.date(), time(0))
        moments = Pastimes(self.conn).moments(today)
        if len(moments) >= self.max_per_day:
            return "enough today"
        if moments and now - datetime.fromisoformat(moments[-1].ts) < MIN_GAP:
            return "too soon"
        his = last_his_message(self.conn)
        if his is not None and now - his < AFTER_HIS_MESSAGE:
            return "talking"
        return None


def render_menu(choices: list[Choice]) -> str:
    lines = []
    for n, c in enumerate(choices, 1):
        lines.append(f"{n}. {c.line}" + (f"（选这个要在 arg 里写：{c.arg_hint}）" if c.arg_hint else ""))
        lines += [f"   {n}.{k} {d}" for k, d in enumerate(c.details, 1)]
    return "\n".join(lines)


def _ints(v) -> list[int]:
    return [x for x in (v if isinstance(v, list) else []) if isinstance(x, int) and not isinstance(x, bool)]


class Leisure:
    def __init__(self, brain: "Brain", activities: list[Activity], *, fetch: Fetch = urllib_fetch,
                 searcher: Searcher | None = None, sources: list[dict] | None = None,
                 rng: random.Random | None = None) -> None:
        self.brain = brain
        self.activities = {a.key: a for a in activities}
        self.fetch = fetch
        self.searcher = searcher
        self.sources = sources
        self.rng = rng or random.Random()

    def kit(self, now: datetime) -> Kit:
        conn = self.brain.conn
        return Kit(conn, now, MemoryStore(conn), Pastimes(conn), self.fetch, self.searcher,
                   self.sources if self.sources is not None else load_sources())

    def menu(self, kit: Kit) -> list[Choice]:
        choices = [NOTHING_AT_HOME if self.brain.cottage is not None else NOTHING]
        for a in self.activities.values():
            try:
                choices += a.offer(kit)
            except Exception:  # noqa: BLE001 - one activity that cannot offer today is left out
                continue
        self.rng.shuffle(choices)  # models favour what comes first; nothing is not the last resort
        return choices

    def run(self, now: datetime | None = None) -> Moment | None:
        now = now or datetime.now()
        brain = self.brain
        policy = LeisurePolicy(brain.conn, enabled=brain.settings.leisure,
                               max_per_day=brain.settings.leisure_max_per_day)
        if policy.refused(now) is not None:
            return None
        kit = self.kit(now)
        moment_id = kit.pastimes.begin_moment(now)
        choices = self.menu(kit)
        data = ask_json(brain.llm, "leisure_choose", persona=brain.persona, now=self.when(now),
                        mood=MoodStore.apply_clock(brain.moods.load(), now, kitchen=brain.cottage is not None).describe(),
                        threads="\n".join(f"- {m.line()}" for m in kit.store.alive("self")[-5:]) or "（没什么特别的）",
                        earlier=self.earlier(kit, now), home=self.home(now), menu=render_menu(choices),
                        temperature=1.0)
        pick = (data or {}).get("pick")
        if not isinstance(pick, int) or not 1 <= pick <= len(choices):
            kit.pastimes.end_moment(moment_id, "nothing", NOTHING.line, "（没想好）")
            return self.finish(kit, moment_id, did_something=False)
        choice = choices[pick - 1]
        why = str((data or {}).get("why") or "").strip()[:80]
        if choice.activity == NOTHING.activity:
            kit.pastimes.end_moment(moment_id, "nothing", choice.line, why)
            return self.finish(kit, moment_id, did_something=False)
        picks = [k - 1 for k in _ints((data or {}).get("items"))]
        arg = str((data or {}).get("arg") or "").strip()[:40]
        try:
            material = self.activities[choice.activity].do(kit, choice, picks, arg)
        except Exception as e:  # noqa: BLE001 - a broken activity is a plan that fell through
            material = Material(result=f"想{choice.line}，没弄成（{type(e).__name__}）")
        ids = self.write_down(kit, choice, why, material) if material.opened else []
        kit.pastimes.end_moment(moment_id, choice.activity, choice.line, why, material.result, ids)
        return self.finish(kit, moment_id, did_something=bool(material.opened) or material.done,
                           moved=material.mood)

    def write_down(self, kit: Kit, choice: Choice, why: str, material: Material) -> list[int]:
        browser = Browser(self.brain.llm, self.brain.persona)
        did = choice.line + (f"（{why}）" if why else "")
        seen, self_notes = browser.read(material.opened, template="leisure_read", did=did)
        ids = []
        for s in seen:
            item = material.opened[s.index][0]
            m = kit.store.note("world", s.text, importance=s.importance, valence=s.valence,
                               tags=tuple(s.tags) + (item.source,), source=item.url, now=kit.now)
            if m is not None:
                ids.append(m.id)
        if self.brain.cottage is not None:  # what she does to her room goes through its rules
            self_notes = [n for n in self_notes if not invented_act(n[0])]
        if self_notes and self.self_notes_today(kit) < SELF_NOTES_PER_DAY:
            text, importance = max(self_notes, key=lambda n: n[1])
            m = kit.store.note("self", text, importance=importance, now=kit.now)
            if m is not None:
                ids.append(m.id)
        return ids

    def self_notes_today(self, kit: Kit) -> int:
        today = datetime.combine(kit.now.date(), time(0))
        return kit.store.count_of_kind("self", [i for m in kit.pastimes.moments(today) for i in m.memories])

    def finish(self, kit: Kit, moment_id: int, *, did_something: bool,
               moved: dict[str, float] | None = None) -> Moment:
        # what the chore did to her body, then what the free moment itself did: two messages, in
        # that order, each kept within 0–100 (docs/nodes_design_zh.md step 4)
        if moved:
            self.brain.bus.publish(MoodMoved(kit.now, hunger=moved.get("hunger", 0.0),
                                             energy=moved.get("energy", 0.0), why="家务"))
        if did_something:
            self.brain.bus.publish(MoodMoved(kit.now, boredom=BOREDOM_AFTER_DOING, why="空闲时做了点事"))
        else:
            self.brain.bus.publish(MoodMoved(kit.now, energy=ENERGY_AFTER_NOTHING, why="空闲时发了会儿呆"))
        return next(m for m in kit.pastimes.moments(kit.now - timedelta(days=1)) if m.id == moment_id)

    def home(self, now: datetime) -> str:
        """Her cottage as it is, when she has one (decision 26): a section of its own, or nothing."""
        cottage = self.brain.cottage
        if cottage is None:
            return ""
        try:
            return "## 你的小屋\n" + layout() + "\n\n屋里现在：\n" + cottage.for_leisure(now) + "\n"
        except ValueError:
            return ""

    @staticmethod
    def when(now: datetime) -> str:
        return f"{now.strftime('%Y-%m-%d')} 周{WEEKDAYS[now.weekday()]} {now.strftime('%H:%M')}"

    @staticmethod
    def earlier(kit: Kit, now: datetime) -> str:
        today = datetime.combine(now.date(), time(0))
        lines = [moment_line(m) for m in kit.pastimes.moments(today, now) if m.choice]
        return "\n".join(f"- {line}" for line in lines) or "（今天还没有）"


class LeisureNode:
    """Her free time as a node (docs/nodes_design_zh.md step 3): on a tick she may have a free
    moment, unless she just texted him at that very moment (she was busy with that)."""

    def __init__(self, run: Callable[[datetime], "Moment | None"]) -> None:
        self.run = run
        self.spoke_at: datetime | None = None

    def on_she_said(self, m: SheSaid) -> None:
        if m.first:
            self.spoke_at = m.at

    def on_time(self, m: TimePassed) -> None:
        if self.spoke_at == m.now:
            return
        self.run(m.now)


def away(m: Moment) -> bool:
    """A free moment that is not one of the things she did to her room: those are in the
    room's own record (decision 26), so they are not listed twice."""
    return bool(m.choice) and m.choice != COTTAGE_KEY


def moment_line(m: Moment) -> str:
    """One plain line for prompts, the diary and `fish show`: "14:30 读了《西遊記》第001回的一段"."""
    what = "什么都没干，发了会儿呆" if m.choice == "nothing" else (m.result or m.line)
    return f"{m.ts[11:16]} {what}"


def pastimes_line(pastimes: Pastimes, now: datetime, limit: int = 3) -> str:
    from fish.brain.leisure.book import KIND as BOOK, where

    bits = [f"在读《{p.title}》（{where(p)}）" if p.kind == BOOK else f"在追「{p.title}」"
            for p in pastimes.active(now)[:limit]]
    return "你" + "、".join(bits) + "。" if bits else ""

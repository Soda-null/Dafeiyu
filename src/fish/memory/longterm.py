"""Long-term memories: the `memories` table and a memory's lifecycle.

add -> (recall) touch -> correct (supersede) / merge -> never deleted.
Data and math only; the text of a memory is written by the brain or the nightly routine.
Field meanings: docs/memory_design_zh.md §4.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from fish.memory import stability as st
from fish.memory.when import day_of, fix_weekday

KINDS = ("fact", "event", "howto", "insight", "self", "world")  # world: things she saw online
PROFILE_IMPORTANCE = 8  # facts at or above this importance form the always-present profile
PROFILE_SIZE = 12
# Card facts that keep him safe come right after the pinned ones (memory v3 §B3).
SAFETY = re.compile(r"过敏|不耐(?!烦)|病|药")

# Choosing before writing (decision 19): what `note` refuses or folds into an old memory.
REPEAT_SIMILARITY = 0.5  # same kind, this much bigram overlap (dates removed): a repeat
FACT_REPEAT_SIMILARITY = 0.8  # facts differ by one number when he corrects himself; stricter
KIND_CAPS = {"insight": 20, "howto": 20}  # beyond this the least stable is pushed out
# Notes about the chat itself (he is testing her memory) are not things about him.
ABOUT_THE_CHAT = re.compile(r"考我|考她|记性|记不记得|试探我|试探她|测我记")
ABOUT_HIM_KINDS = ("fact", "event", "insight", "howto")
GIST_AT = (3, 6, 12, 24, 48, 96)  # times at which a repeated thing is rewritten as a gist
# Only for things that happen (his events, her own doings). A fact, a rule or an insight said again
# is the same thing confirmed, not something that happened again: counted, never "好几回".
HAPPENING_KINDS = ("event", "self")
# Insights and howto rules start unconfirmed (decision 21): they need evidence on this many
# different days before they get the strength of a fact about him.
RULE_KINDS = ("insight", "howto")
EVIDENCE_DAYS = 3
UNCONFIRMED = "待印证"
# Words that make a "him himself" note a passing state (a sore throat last week), not who he is.
FOR_NOW = re.compile(r"最近|这几天|这阵子|这周|上周|今天|昨天|刚才|还没好|这次|暂时|目前|这两天")
_DATE = re.compile(r"\d{4}\s*[-年/.]\s*\d{1,2}\s*[-月/.]\s*\d{1,2}\s*日?")
# Why a memory stopped being current (memory v3). Only a correction he made and an update the
# night found are "what she used to think"; a memory merged away or pushed out by a cap is not.
WHYS = ("correct", "update", "merge", "cap", "expired")
SHOWN_AS_FORMER = ("correct", "update")


def strongest_about(abouts: list[str | None]) -> str | None:
    """What a merged memory is about: the strongest of its sources (一辈子 > 本人 > 日常 > 路过).
    It stays unconfirmed only when every source was; a merge is not evidence."""
    known = [a for a in abouts if a in st.ABOUTS]
    if known:
        return max(known, key=st.ABOUTS.index)
    return UNCONFIRMED if abouts and all(a == UNCONFIRMED for a in abouts) else None


def _bigrams(text: str) -> set[str]:
    chars = [c for c in _DATE.sub("", text) if c.isalnum()]
    return {a + b for a, b in zip(chars, chars[1:])}


def overlap(a: str, b: str) -> float:
    """Dice overlap of character bigrams with dates taken out: "he had lab on 10-26" and
    "he had lab on 10-27" are the same words."""
    x, y = _bigrams(a), _bigrams(b)
    return 2 * len(x & y) / (len(x) + len(y)) if x and y else 0.0


def iso(now: datetime) -> str:
    return now.isoformat(timespec="seconds")


def days_between(earlier: str, now: datetime) -> float:
    return (now - datetime.fromisoformat(earlier)).total_seconds() / 86400


@dataclass(frozen=True)
class Memory:
    id: int
    kind: str
    text: str
    created: str
    source_episode: int | None
    importance: int
    valence: float
    arousal: float
    stability: float
    last_recalled: str
    recall_count: int
    superseded_by: int | None
    merged_from: tuple[int, ...]
    tags: tuple[str, ...]
    pinned: bool
    source: str | None = None  # kind=world: where she saw it
    times: int = 1  # how many times it happened or was said (decision 20)
    gist_due: bool = False  # often enough now to be rewritten as a gist tonight
    pattern: str | None = None  # how one time of it was worded, kept when the text became a gist
    about: str | None = None  # 路过 / 日常 / 本人 / 一辈子, or 待印证 for a rule not yet confirmed
    last_time: str | None = None  # YYYY-MM-DD it last happened; a day counts once
    why: str | None = None  # why it was superseded (WHYS); None while current, or before v3
    happened_on: str | None = None  # YYYY-MM-DD it happened (or will); None before v3

    @property
    def unconfirmed(self) -> bool:
        return self.about == UNCONFIRMED

    @property
    def often(self) -> str:
        """How she feels about how often: nothing, 好几回, 很多回 (only for things that happen)."""
        if self.kind not in HAPPENING_KINDS or self.times < 2:
            return ""
        return "好几回了" if self.times < 5 else "很多回了"

    def line(self) -> str:
        """The text as it goes into a prompt: with "（很多回了）" when it kept happening, and
        "（还说不准）" for a rule she has not seen confirmed yet."""
        if self.unconfirmed:
            return f"{self.text}（还说不准）"
        return f"{self.text}（{self.often}）" if self.often else self.text

    def retrievability(self, now: datetime) -> float:
        return st.retrievability(self.stability, days_between(self.last_recalled, now))

    def fuzzy(self, now: datetime) -> bool:
        return self.retrievability(now) < st.FUZZY_R

    @property
    def alive(self) -> bool:
        return self.superseded_by is None


def card_order(m: Memory) -> tuple:
    """Sort key of her card: pinned, then safety, then the latest day it came up."""
    last = date.fromisoformat(m.last_time or m.created[:10])
    return (not m.pinned, not SAFETY.search(m.text), -last.toordinal(), -m.importance, m.id)


def _from_row(r: sqlite3.Row) -> Memory:
    return Memory(
        id=r["id"], kind=r["kind"], text=r["text"], created=r["created"],
        source_episode=r["source_episode"], importance=r["importance"],
        valence=r["valence"], arousal=r["arousal"], stability=r["stability"],
        last_recalled=r["last_recalled"], recall_count=r["recall_count"],
        superseded_by=r["superseded_by"],
        merged_from=tuple(json.loads(r["merged_from"] or "[]")),
        tags=tuple(json.loads(r["tags"] or "[]")),
        pinned=bool(r["pinned"]),
        source=r["source"] if "source" in r.keys() else None,
        times=r["times"] if "times" in r.keys() else 1,
        gist_due=bool(r["gist_due"]) if "gist_due" in r.keys() else False,
        pattern=r["pattern"] if "pattern" in r.keys() else None,
        about=r["about"] if "about" in r.keys() else None,
        last_time=r["last_time"] if "last_time" in r.keys() else None,
        why=r["why"] if "why" in r.keys() else None,
        happened_on=r["happened_on"] if "happened_on" in r.keys() else None,
    )


def _why_before_v3(old: Memory, new: Memory) -> str:
    """A memory superseded before the `why` column existed: guessed the way the v3 migration
    does (docs/memory_v3_zh.md §8). A source of a merge was merged; a rule replaced by another
    rule, not merged, was pushed out by the cap; anything else was an update."""
    if old.id in new.merged_from:
        return "merge"
    if old.kind in RULE_KINDS and new.kind == old.kind:
        return "cap"
    return "update"


class MemoryStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # --- write -------------------------------------------------------------

    def add(
        self,
        kind: str,
        text: str,
        *,
        importance: int,
        valence: float = 0.0,
        arousal: float = 0.0,
        source_episode: int | None = None,
        tags: tuple[str, ...] | list[str] = (),
        pinned: bool = False,
        stability: float | None = None,
        merged_from: tuple[int, ...] | list[int] = (),
        source: str | None = None,
        now: datetime | None = None,
        happened_on: str | None = None,
    ) -> Memory:
        """happened_on: the day it happened; by default the one day its text names, else today."""
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
        now = now or datetime.now()
        importance = st.clamp_importance(importance)
        pinned = pinned or importance >= st.PINNED_IMPORTANCE
        if stability is None:
            stability = st.initial_stability(importance, valence)
        if pinned:
            stability = st.INFINITE
        happened_on = happened_on or (day_of(text, now) or now.date()).isoformat()
        cur = self.conn.execute(
            "INSERT INTO memories (kind, text, created, source_episode, importance, valence, arousal,"
            " stability, last_recalled, recall_count, superseded_by, merged_from, tags, pinned, source,"
            " happened_on) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, ?, ?, ?)",
            (kind, text, iso(now), source_episode, importance, valence, arousal, stability,
             iso(now), json.dumps(list(merged_from)), json.dumps(list(tags), ensure_ascii=False),
             int(pinned), source, happened_on),
        )
        self.conn.commit()
        return self.get(cur.lastrowid)

    def note(self, kind: str, text: str, *, importance: int, now: datetime | None = None,
             said: str = "", **fields) -> Memory | None:
        """How the brain and the routines write (decision 19): choose before writing.

        None: not written (it is about the chat itself, not about him). An older memory:
        this was a repeat, so the old one was recalled instead. Otherwise the new memory;
        if its kind is over its cap, the least stable one of that kind is pushed out.
        said: his line the note came from; its time words date the note when the note's own
        text names no day (memory v3 §B1). A date that disagrees with the weekday written
        next to it is moved to that weekday first (§B2 D5)."""
        now = now or datetime.now()
        text = fix_weekday(text, now.date())
        if kind in ABOUT_HIM_KINDS and ABOUT_THE_CHAT.search(text):
            return None
        if kind == "self" and text.lstrip().startswith(("他", "她")):
            return None  # her life threads are about her; his things are noted in chat
        # (the persona calls him 他 or 她, FISH_OWNER; she is never the subject in third person)
        about = fields.pop("about", None)
        if about == "本人" and FOR_NOW.search(text):
            about = "日常"  # a state for now is not who he is; it does not go on his card
        same = self.repeat_of(kind, text, now, lifelong=about == "一辈子")
        if same is not None:
            return self.happened_again(same.id, now)
        if kind in RULE_KINDS:
            about = UNCONFIRMED  # however sure the model sounds, one day is one day
            fields["stability"] = st.UNCONFIRMED_DAYS
        elif about in st.ABOUTS:
            fields["stability"] = st.stability_from(about, fields.get("arousal", 0.0))
            fields["pinned"] = about == "一辈子"
        if "stability" in fields:
            importance = st.importance_of(fields["stability"])
        fields.setdefault("happened_on", (day_of(text, now, said) or now.date()).isoformat())
        new = self.add(kind, text, importance=importance, now=now, **fields)
        self.conn.execute("UPDATE memories SET about = ?, last_time = ? WHERE id = ?",
                          (about, iso(now)[:10], new.id))
        self.conn.commit()
        new = self.get(new.id)
        cap = KIND_CAPS.get(kind)
        if cap is not None:
            others = [m for m in self.alive(kind) if m.id != new.id and not m.pinned]
            for weakest in sorted(others, key=lambda m: (m.stability, m.id))[:max(0, len(others) + 1 - cap)]:
                self.supersede(weakest.id, new.id, why="cap")
        return new

    def repeat_of(self, kind: str, text: str, now: datetime, *, lifelong: bool = False) -> Memory | None:
        """The live memory this text repeats, if any. Across days too (decision 20): the
        same thing every Friday is one memory that happened many times. A lifelong fact (his
        birthday) said in other words is still the same one: against pinned facts the bar
        is the ordinary one, not the strict one for facts."""
        threshold = FACT_REPEAT_SIMILARITY if kind == "fact" else REPEAT_SIMILARITY
        best: tuple[float, Memory] | None = None
        for m in self.alive(kind):
            sim = max(overlap(text, m.text), overlap(text, m.pattern) if m.pattern else 0.0)
            if lifelong and m.pinned and sim >= REPEAT_SIMILARITY:
                sim = max(sim, threshold)
            if sim >= threshold and (best is None or sim > best[0]):
                best = (sim, m)
        return best[1] if best else None

    def happened_again(self, memory_id: int, now: datetime | None = None) -> Memory:
        """The same thing once more: recalled once; on a new day, one more time, flagged for
        a gist rewrite at 3, 6, 12, ... A rule seen on its third day is confirmed: it gets the
        strength of a fact about him (decision 21)."""
        now = now or datetime.now()
        m = self.touch(memory_id, now)
        today = iso(now)[:10]
        if m.last_time == today:
            return m  # said twice the same day: still one time
        times = m.times + 1
        due = times in GIST_AT and m.kind in HAPPENING_KINDS
        self.conn.execute("UPDATE memories SET times = ?, gist_due = gist_due OR ?, last_time = ? WHERE id = ?",
                          (times, int(due), today, memory_id))
        if m.unconfirmed and times >= EVIDENCE_DAYS:
            s = max(m.stability, st.stability_from("本人", m.arousal))
            self.conn.execute("UPDATE memories SET about = '本人', stability = ?, importance = ? WHERE id = ?",
                              (s, st.importance_of(s), memory_id))
        self.conn.commit()
        return self.get(memory_id)

    def weaken(self, memory_id: int, now: datetime | None = None) -> Memory:
        """She sees a rule is no longer true: it fades within days instead of lasting."""
        now = now or datetime.now()
        self.conn.execute("UPDATE memories SET stability = MIN(stability, ?), last_recalled = ? WHERE id = ?",
                          (st.WEAKENED_DAYS, iso(now), memory_id))
        self.conn.commit()
        return self.get(memory_id)

    def gists_due(self) -> list[Memory]:
        rows = self.conn.execute("SELECT * FROM memories WHERE gist_due = 1 AND superseded_by IS NULL"
                                 " ORDER BY id")
        return [_from_row(r) for r in rows]

    def rewrite_as_gist(self, memory_id: int, text: str) -> Memory:
        """Nightly: the one-off details are gone, the gist stays; same memory, same strength."""
        self.conn.execute("UPDATE memories SET pattern = COALESCE(pattern, text), text = ?, gist_due = 0"
                          " WHERE id = ?", (text, memory_id))
        self.conn.commit()
        return self.get(memory_id)

    def touch(self, memory_id: int, now: datetime | None = None) -> Memory:
        """She just used this memory: it gets stronger, more so if it was nearly gone."""
        now = now or datetime.now()
        m = self.get(memory_id)
        new_s = st.after_recall(m.stability, m.retrievability(now))
        self.conn.execute(
            "UPDATE memories SET stability = ?, last_recalled = ?, recall_count = recall_count + 1"
            " WHERE id = ?",
            (new_s, iso(now), memory_id),
        )
        self.conn.commit()
        return self.get(memory_id)

    def supersede(self, old_id: int, new_id: int, *, why: str) -> None:
        if why not in WHYS:
            raise ValueError(f"why must be one of {WHYS}, got {why!r}")
        self.conn.execute("UPDATE memories SET superseded_by = ?, why = ? WHERE id = ?",
                          (new_id, why, old_id))
        self.conn.commit()

    def correct(
        self, old_id: int, text: str, *, importance: int | None = None,
        now: datetime | None = None,
    ) -> Memory:
        """He corrected her: a new memory replaces the old one, which stays as 'what she used to think'.
        It keeps what the old one was about (his major corrected is still about him himself), and
        the day it happened unless the new words name another one."""
        old = self.get(old_id)
        now = now or datetime.now()
        importance = old.importance if importance is None else importance
        fresh = st.initial_stability(importance, old.valence)
        stability = max(fresh, old.stability) if fresh != st.INFINITE else st.INFINITE
        new = self.add(
            old.kind, text, importance=importance, valence=old.valence, arousal=old.arousal,
            source_episode=old.source_episode, tags=old.tags, pinned=old.pinned,
            stability=stability, now=now,
            happened_on=(d.isoformat() if (d := day_of(text, now)) else old.happened_on),
        )
        self.conn.execute("UPDATE memories SET about = ?, last_time = ? WHERE id = ?",
                          (old.about, iso(now)[:10], new.id))
        self.supersede(old_id, new.id, why="correct")
        return self.get(new.id)

    def merge(self, ids: list[int], text: str, *, now: datetime | None = None) -> Memory:
        """Nightly: several near-duplicates become one, more stable, with its sources noted.
        What it is about, whether it is pinned and the day it last happened carry over; so does
        the day it happened (the latest of its sources), unless the merged words name one."""
        olds = [self.get(i) for i in ids]
        if not olds:
            raise ValueError("merge needs at least one memory")
        now = now or datetime.now()
        tags: list[str] = []
        for o in olds:
            tags += [t for t in o.tags if t not in tags]
        new = self.add(
            olds[0].kind, text,
            importance=max(o.importance for o in olds),
            valence=sum(o.valence for o in olds) / len(olds),
            arousal=max(o.arousal for o in olds),
            source_episode=olds[0].source_episode, tags=tags,
            pinned=any(o.pinned for o in olds),
            stability=st.after_merge(*(o.stability for o in olds)),
            merged_from=ids, now=now,
            happened_on=(d.isoformat() if (d := day_of(text, now))
                         else max((o.happened_on for o in olds if o.happened_on), default=None)),
        )
        for o in olds:
            self.supersede(o.id, new.id, why="merge")
        times = sum(o.times for o in olds)  # both counts carry over (decision 20)
        last = max((o.last_time for o in olds if o.last_time), default=None)
        self.conn.execute("UPDATE memories SET times = ?, about = ?, last_time = ? WHERE id = ?",
                          (times, strongest_about([o.about for o in olds]), last, new.id))
        self.conn.commit()
        return self.get(new.id)

    # --- read --------------------------------------------------------------

    def get(self, memory_id: int) -> Memory:
        row = self.conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if row is None:
            raise KeyError(f"no memory {memory_id}")
        return _from_row(row)

    def alive(self, kind: str | None = None) -> list[Memory]:
        sql = "SELECT * FROM memories WHERE superseded_by IS NULL"
        args: tuple = ()
        if kind:
            sql += " AND kind = ?"
            args = (kind,)
        return [_from_row(r) for r in self.conn.execute(sql + " ORDER BY id", args)]

    def profile(self, limit: int = PROFILE_SIZE) -> list[Memory]:
        """The facts she always keeps in mind (her card): pinned first, then what keeps him
        safe (allergies, illness, medicine), then the rest by when it last came up. Facts about
        him himself (about = 本人, decision 21) always qualify. Not by stability (memory v3
        §B3): how strongly she holds a fact says nothing about whether it is who he is now."""
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE superseded_by IS NULL AND kind = 'fact'"
            " AND (pinned = 1 OR importance >= ? OR about = '本人')", (PROFILE_IMPORTANCE,)
        )
        return sorted(map(_from_row, rows), key=card_order)[:limit]

    def howto_card(self, limit: int = 8) -> list[Memory]:
        """How to get along with him: the rules she has drawn, always in mind (decision 11).
        A rule she saw is outdated (weakened) leaves the card until it is seen again."""
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE superseded_by IS NULL AND kind = 'howto' AND stability > ?"
            " ORDER BY importance DESC, stability DESC, id DESC LIMIT ?", (st.WEAKENED_DAYS, limit)
        )
        return [_from_row(r) for r in rows]

    def planned_for(self, days: list[date]) -> list[Memory]:
        """Things he said would happen on these days (an exam, a trip), said before the day came:
        what the "today" section reminds her of (memory v3 §B3). A note written on the day it is
        about is not a plan, it is news, and the chat it came from is still in front of her."""
        wanted = [d.isoformat() for d in days]
        rows = self.conn.execute(
            f"SELECT * FROM memories WHERE superseded_by IS NULL AND kind IN ('event', 'fact')"
            f" AND happened_on IN ({', '.join('?' * len(wanted))}) AND substr(created, 1, 10) < happened_on"
            " ORDER BY happened_on, id", wanted)
        return [_from_row(r) for r in rows]

    def seen_recently(self, now: datetime, days: int = 7) -> list[Memory]:
        """World memories from the last `days`, newest first (also the URLs not to reopen)."""
        since = iso(now - timedelta(days=days))
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE kind = 'world' AND created >= ? ORDER BY id DESC", (since,)
        )
        return [_from_row(r) for r in rows]

    def former(self, memory_id: int) -> Memory | None:
        """The memory this one replaced, if any ('你之前说是周五来着'): only a correction or an
        update, never a source it was merged from or a rule a cap pushed out."""
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE superseded_by = ? ORDER BY id DESC", (memory_id,)
        ).fetchall()
        new = self.get(memory_id) if rows else None
        for old in map(_from_row, rows):
            if (old.why or _why_before_v3(old, new)) in SHOWN_AS_FORMER:
                return old
        return None

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

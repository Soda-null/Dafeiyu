"""Nightly routine (docs/memory_design_zh.md §5.4), once per "fish day".

Her day ends at NIGHT_BOUNDARY (03:30): a chat at 01:00 on the 27th still belongs to the
26th. `diary_day(now)` is the day being closed; `routine_runs.nightly` holds the last one
done, so the 03:30 timer and a catch-up at the next start never do the same day twice.

Steps (model steps need a Brain; without one only the mechanical ones run):
  1. close a stale open episode (model)      5. write her diary, keep her life threads (model)
  2. merge near-duplicates (model)           6. old episodes lose detail
  3. new facts that replace old ones (model) 7. follow-ups she never got to ask are let go
  4. weekly reflection (model)               8. export data/notebook_export.md
  6b. what he says on one weekday, counted (code, memory v3 §B6)
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from fish.brain.consolidate import Consolidator, similarity
from fish.brain.leisure import away, moment_line
from fish.cottage import invented_act
from fish.memory import (Diary, EpisodeManager, Memory, MemoryStore, Pastimes, PhaseStore,
                         ProspectiveStore, Relationship, TraitStore, count_patterns, overlap)
from fish.mood import MoodStore
from fish.routines.export import export_notebook
from fish.routines.runs import claim_run, last_run, mark_run
from fish.routines.stickers import adopt_inbox_stickers

if TYPE_CHECKING:
    from fish.brain.respond import Brain

NIGHT_BOUNDARY = time(3, 30)
MERGE_SIMILARITY = 0.4  # bigram Dice; the model makes the final call, this only picks candidates
# "住 3 号楼" and "搬到了七号楼" must look alike to the update check: numerals become digits.
_NUMERALS = str.maketrans("〇零一二两三四五六七八九", "001223456789")
SELF_NOTES_PER_NIGHT = 1  # decision 19: her life grows by one thread a night at most
MAX_PAIRS = 10
MAX_CANDIDATES = 5
REFLECT_EVERY_DAYS = 7
REFLECT_AFTER_EPISODES = 5
GROWTH_EVERY_DAYS = 30  # layer A looks back about once a month
EXPORT_PATH = Path("data/notebook_export.md")


def fish_day(ts: datetime) -> date:
    return ts.date() if ts.time() >= NIGHT_BOUNDARY else ts.date() - timedelta(days=1)


def diary_day(now: datetime) -> date:
    """The day the night closes: yesterday once the boundary has passed."""
    return fish_day(now) - timedelta(days=1)


def strongest(notes: list[tuple[str, int]], n: int) -> list[tuple[str, int]]:
    """Her life grows by at most n threads a night (decision 19): keep the most important."""
    return sorted(notes, key=lambda x: -x[1])[:n]


def _new_today(store: MemoryStore, day: date) -> list[Memory]:
    return [m for m in store.alive() if fish_day(datetime.fromisoformat(m.created)) == day]


def _merge_pairs(new: list[Memory], alive: list[Memory]) -> list[tuple[Memory, Memory]]:
    pairs: list[tuple[Memory, Memory]] = []
    seen: set[frozenset[int]] = set()
    for a in new:
        for b in alive:
            if a.id == b.id or a.kind != b.kind or frozenset((a.id, b.id)) in seen:
                continue
            if similarity(a.text, b.text) >= MERGE_SIMILARITY:
                pairs.append((a, b) if a.id > b.id else (b, a))
                seen.add(frozenset((a.id, b.id)))
    return pairs[:MAX_PAIRS]


def _update_groups(new: list[Memory], alive: list[Memory],
                   merged_away: set[int]) -> list[tuple[Memory, list[Memory]]]:
    """Each new fact with the older facts it might replace. No upper bound on likeness: a pair
    the merge step declined ("住 3 号楼" / "住七号楼") is exactly a changed fact. Any shared
    words or tag make a candidate; the model decides, and "拿不准就不列". An open promise is
    never one: only he can call it off, and the close of that chat says so (memory v3 §B4)."""
    groups = []
    for n in new:
        if n.kind != "fact" or n.id in merged_away:
            continue
        olds = []
        for o in alive:
            if (o.id == n.id or o.kind != "fact" or o.id in merged_away or o.created >= n.created
                    or o.pact_state == "open"):
                continue
            shared_tag = bool(set(n.tags) & set(o.tags))
            sim = overlap(n.text.translate(_NUMERALS), o.text.translate(_NUMERALS))
            if shared_tag or sim > 0:
                olds.append(((shared_tag, sim), o))
        if olds:
            olds.sort(key=lambda s: s[0], reverse=True)
            groups.append((n, [o for _, o in olds[:MAX_CANDIDATES]]))
    return groups[:MAX_PAIRS]


def _change_groups(new: list[Memory], alive: list[Memory],
                   merged_away: set[int]) -> list[tuple[Memory, list[Memory]]]:
    """Each new event of his with the older facts it might make untrue (memory v3 §11 item 7,
    approved 10-28): "他说又喝回原来那个了" was kept as a fading event while the fact on her
    card still said he had switched. Same candidates as `_update_groups`, from events."""
    groups = []
    for n in new:
        if n.kind != "event" or n.id in merged_away or n.text.lstrip().startswith("我"):
            continue
        olds = []
        for o in alive:
            if (o.kind != "fact" or o.id in merged_away or o.created >= n.created
                    or o.pact_state == "open"):
                continue
            shared_tag = bool(set(n.tags) & set(o.tags))
            sim = overlap(n.text.translate(_NUMERALS), o.text.translate(_NUMERALS))
            if shared_tag or sim > 0:
                olds.append(((shared_tag, sim), o))
        if olds:
            olds.sort(key=lambda s: s[0], reverse=True)
            groups.append((n, [o for _, o in olds[:MAX_CANDIDATES]]))
    return groups[:MAX_PAIRS]


def run_nightly(conn: sqlite3.Connection, now: datetime | None = None, *,
                brain: "Brain | None" = None, export_path: Path | None = None) -> dict:
    now = now or datetime.now()
    day = diary_day(now)
    if last_run(conn, "nightly") == day.isoformat() or not claim_run(conn, "nightly", day.isoformat()):
        return {"skipped": True}
    report: dict = {"skipped": False, "day": day.isoformat()}

    store = MemoryStore(conn)
    episodes = EpisodeManager(conn)
    thinker = Consolidator(brain.llm, brain.persona) if brain else None

    # 1. a chat that trailed off without being closed
    stale = episodes.stale(now)
    if stale is not None and brain is not None:
        brain.close_episode(stale, now)
        report["closed"] = stale.id

    new = _new_today(store, day)
    # every note the pact words caught today (memory v3 §B2 D1/D2), to be read over
    caught = [m.id for m in store.alive() if m.pact and (m in new or m.last_time == day.isoformat())]
    if caught:
        report["pacts"] = caught

    # 2. duplicates -> one stronger memory
    merged_away: set[int] = set()
    if thinker:
        for m in thinker.merge_pairs(_merge_pairs(new, store.alive())):
            if all(store.get(i).alive for i in m.ids):
                store.merge(list(m.ids), m.text, now=now)
                merged_away.update(m.ids)
        report["merged"] = len(merged_away) // 2

    # 3. a new fact that replaces an old one
    if thinker:
        updates = thinker.find_updates(_update_groups(new, store.alive(), merged_away))
        done = 0
        for u in updates:
            if store.get(u.old_id).alive and store.get(u.new_id).alive:
                store.supersede(u.old_id, u.new_id, why="update")
                done += 1
        report["updated"] = done
        # 3a. a new event of his that makes an old fact untrue: the fact is rewritten as it is now
        rewritten = 0
        for old_id, text in thinker.rewrite_facts(_change_groups(new, store.alive(), merged_away)):
            if store.get(old_id).alive:
                store.correct(old_id, text, now=now)
                rewritten += 1
        report["rewritten"] = rewritten

    # 3b. things that kept happening -> one gist each, without one-off details (decision 20)
    if thinker:
        repeated = store.gists_due()
        if repeated:
            rewritten = thinker.gists(repeated)
            for memory_id, text in rewritten.items():
                store.rewrite_as_gist(memory_id, text)
            report["gists"] = len(rewritten)

    # 4. reflection: every 7 days, or after 5 chats
    if thinker:
        last_reflect = last_run(conn, "reflect")
        recent = episodes.recent(REFLECT_AFTER_EPISODES * 2)
        # only chats from days after the last reflection: re-reading the same chats is not new
        # evidence, so a rule seen again here has really been seen again (decision 21)
        since = [e for e in recent if not last_reflect
                 or fish_day(datetime.fromisoformat(e.started)) > date.fromisoformat(last_reflect)]
        due = (not last_reflect or (day - date.fromisoformat(last_reflect)).days >= REFLECT_EVERY_DAYS
               or len(since) >= REFLECT_AFTER_EPISODES)
        if due and since:
            gists = [e.gist or e.summary[:60] for e in reversed(since) if e.gist or e.summary]
            facts = store.profile() + [m for m in store.alive("fact") if m not in store.profile()][:20]
            old = store.alive("insight")  # all of them (at most 20): she may see some are outdated
            old_howto = store.alive("howto")
            # rules written during the chats she now looks back on are that evidence itself: she
            # can neither call them outdated nor see them "again" (memory v3 step 1). The last
            # look back's own rules came before these chats, so these chats are new evidence for
            # them; tonight's merges (created now) are not evidence either way. Before the run
            # time was kept, the first of these chats marks the start.
            at = last_run(conn, "reflect_at")
            start = (datetime.fromisoformat(at) if at else
                     min(datetime.fromisoformat(e.started) for e in since))
            newer = {m.id for m in old + old_howto
                     if start < datetime.fromisoformat(m.created) < now}
            insights, howtos, outdated, confirms = thinker.reflect(gists, facts, old, old_howto, newer=newer)
            for memory_id in outdated:
                store.weaken(memory_id, now)
            for memory_id in confirms:
                store.happened_again(memory_id, now)
            report["outdated"] = len(outdated)
            report["confirmed"] = len(confirms)
            for text, importance in insights:
                store.note("insight", text, importance=importance, now=now)
            for text, importance in howtos:
                store.note("howto", text, importance=importance, now=now)
            mark_run(conn, "reflect", day.isoformat())
            mark_run(conn, "reflect_at", now.isoformat())  # the time, not the day: see `newer`
            report["insights"] = len(insights)
            report["howto"] = len(howtos)

    # 5. her diary and her own life (no diary for days before she met him); the diary call also
    #    rewrites layer B's sentence, slowly
    moods = MoodStore(conn)
    phases = PhaseStore(conn)
    day_start = datetime.combine(day, NIGHT_BOUNDARY)
    day_end = datetime.combine(day + timedelta(days=1), NIGHT_BOUNDARY)
    first = conn.execute("SELECT MIN(ts) FROM messages").fetchone()[0]
    born = fish_day(datetime.fromisoformat(first)) if first else None
    line: str | None = None
    if thinker and born is not None and day >= born:
        diary = Diary(conn)
        todays = [e for e in episodes.recent(20)
                  if fish_day(datetime.fromisoformat(e.started)) == day and (e.gist or e.summary)]
        gists = [e.gist or e.summary[:60] for e in reversed(todays)]
        threads = [m.line() for m in store.alive("self")][-5:]
        yesterday = next((t for d, t in diary.recent(1) if d < day.isoformat()), "")
        seen_today = [m.text for m in store.seen_recently(now, 2)
                      if fish_day(datetime.fromisoformat(m.created)) == day]
        leisure = [moment_line(m) for m in Pastimes(conn).moments(day_start, day_end) if away(m)]
        home: list[str] | None = None
        if brain.cottage is not None:  # what she did at home, meals, food gone off (decision 26)
            try:
                home = brain.cottage.between(day_start, day_end)
            except ValueError:
                home = []
        prev = phases.current()
        text, notes, line = thinker.diary(day.isoformat(), moods.load().describe(), threads, gists,
                                          yesterday, seen=seen_today, phase_line=prev.line,
                                          tone_word=prev.tone_word, drive_word=prev.drive_word,
                                          leisure=leisure, home=home)
        if text:
            diary.write(day.isoformat(), text)
            if home is not None:  # with a room, what she did is in it; her notes keep thoughts
                notes = [n for n in notes if not invented_act(n[0])]
            for note, importance in strongest(notes, SELF_NOTES_PER_NIGHT):
                store.note("self", note, importance=importance, now=now)
            report["diary"] = True
        else:
            line = None

    # 5b. layer B steps a fifth of the way toward what the day showed (decision 13)
    tone_today, energy_today = moods.day_tone(day_start, day_end)
    focus = [re.sub(r"^[\d\-年月日，, ]+", "", m.text).split("，")[0][:16]
             for m in store.alive("self")][-3:]  # short handles, not whole notes
    phase = phases.update(day.isoformat(), tone_today=tone_today,
                          drive_today=None if energy_today is None else energy_today / 100,
                          focus=focus, line=line)
    report["phase"] = {"tone": round(phase.tone, 2), "drive": round(phase.drive, 2)}

    # 5c. layer A, about once a month: she looks back and may move a slider a notch
    rel = Relationship(conn)
    if thinker:
        known = rel.days_known(now)
        traits = TraitStore(conn)
        last = traits.growth_notes(1)
        last_day = date.fromisoformat(last[0].month) if last else None
        if known >= GROWTH_EVERY_DAYS and (last_day is None or (day - last_day).days >= GROWTH_EVERY_DAYS):
            month_diary = [f"{d}：{t}" for d, t in Diary(conn).recent(GROWTH_EVERY_DAYS)]
            trend = [f"{p.day}：基调{p.tone_word}，劲头{p.drive_word}" for p in phases.history(GROWTH_EVERY_DAYS)][::7]
            note, changes = thinker.grow(day.isoformat(), known, month_diary, trend, traits.describe_all())
            applied = traits.apply(changes, now)
            if note:
                traits.add_growth(day.isoformat(), note, applied)
                store.add("self", f"{day.isoformat()[:7]} 回头看自己：{note}", importance=6, now=now)
            report["growth"] = applied

    # 6. old chats lose detail; 7. follow-ups she never got to ask; and she sleeps
    talked = conn.execute("SELECT 1 FROM messages WHERE role = 'user' AND ts >= ? AND ts < ? LIMIT 1",
                          (day_start.isoformat(timespec="seconds"), day_end.isoformat(timespec="seconds"))
                          ).fetchone() is not None
    moods.rest(tone=phase.tone, drive=phase.drive)
    if not talked:
        rel.quiet_day(now)
    report["compressed"] = episodes.compress(now)
    # 6b. what he says on one weekday ("今天食堂有糖醋排骨" six Fridays running), counted by code
    #     and shown to her on that weekday; never an insight she saw herself (memory v3 §B6)
    patterns = count_patterns(conn, now, rel.patterns())
    rel.set_patterns(patterns, now)
    report["weekday_patterns"] = sum(p["status"] == "active" for p in patterns)
    # a follow-up she never got to ask is let go, not written down as "我一直没问成他" (memory v3:
    # those events crowded out what he said)
    report["expired"] = len(ProspectiveStore(conn).expire(now))

    # 8. the readable export
    if export_path is not None:
        export_notebook(conn, now, export_path)

    # 9. stickers he dropped into the inbox folder get a caption in her words (decision 12)
    if brain is not None:
        report["stickers_added"] = adopt_inbox_stickers(brain, now)

    return report

"""Nightly routine (docs/memory_design_zh.md §5.4), once per "fish day".

Her day ends at NIGHT_BOUNDARY (03:30): a chat at 01:00 on the 27th still belongs to the
26th. `diary_day(now)` is the day being closed; `routine_runs.nightly` holds the last one
done, so the 03:30 timer and a catch-up at the next start never do the same day twice.

Steps (model steps need a Brain; without one only the mechanical ones run):
  1. close a stale open episode (model)      5. write her diary, keep her life threads (model)
  2. merge near-duplicates (model)           6. old episodes lose detail
  3. new facts that replace old ones (model) 7. follow-ups she never got to ask become events
  4. weekly reflection (model)               8. export data/notebook_export.md
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from fish.brain.consolidate import Consolidator, similarity
from fish.config import owner_words
from fish.memory import (Diary, EpisodeManager, Memory, MemoryStore, PhaseStore, ProspectiveStore,
                         Relationship, TraitStore)
from fish.mood import MoodStore
from fish.routines.export import export_notebook
from fish.routines.runs import claim_run, last_run, mark_run

if TYPE_CHECKING:
    from fish.brain.respond import Brain

NIGHT_BOUNDARY = time(3, 30)
EXPIRED_IMPORTANCE = 3
MERGE_SIMILARITY = 0.4  # bigram Dice; the model makes the final call, this only picks candidates
RELATED_SIMILARITY = 0.15
SELF_NOTES_PER_NIGHT = 1  # decision 19: her life grows by one thread a night at most
MAX_PAIRS = 10
MAX_CANDIDATES = 3
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
    groups = []
    for n in new:
        if n.kind != "fact" or n.id in merged_away:
            continue
        olds = []
        for o in alive:
            if o.id == n.id or o.kind != "fact" or o.id in merged_away or o.created >= n.created:
                continue
            shared_tag = bool(set(n.tags) & set(o.tags))
            sim = similarity(n.text, o.text)
            if shared_tag or RELATED_SIMILARITY <= sim < MERGE_SIMILARITY:
                olds.append((sim, o))
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
                store.supersede(u.old_id, u.new_id)
                done += 1
        report["updated"] = done

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
            insights, howtos, outdated = thinker.reflect(gists, facts, old, old_howto)
            for memory_id in outdated:
                store.weaken(memory_id, now)
            report["outdated"] = len(outdated)
            for text, importance in insights:
                store.note("insight", text, importance=importance, now=now)
            for text, importance in howtos:
                store.note("howto", text, importance=importance, now=now)
            mark_run(conn, "reflect", day.isoformat())
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
        prev = phases.current()
        text, notes, line = thinker.diary(day.isoformat(), moods.load().describe(), threads, gists,
                                          yesterday, seen=seen_today, phase_line=prev.line,
                                          tone_word=prev.tone_word, drive_word=prev.drive_word)
        if text:
            diary.write(day.isoformat(), text)
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
    expired = ProspectiveStore(conn).expire(now)
    for f in expired:
        store.add("event", owner_words("我一直没问成他：") + f.text, importance=EXPIRED_IMPORTANCE, valence=-0.2, now=now)
    report["expired"] = len(expired)

    # 8. the readable export
    if export_path is not None:
        export_notebook(conn, now, export_path)

    # 9. stickers he dropped into the inbox folder get a caption in her words (decision 12)
    if brain is not None:
        report["stickers_added"] = adopt_inbox_stickers(brain, now)

    return report


STICKER_TYPES = (".jpg", ".jpeg", ".png", ".gif", ".webp")


def adopt_inbox_stickers(brain: "Brain", now: datetime, limit: int = 10) -> int:
    """Each picture under data/stickers/inbox/ becomes a sticker with a caption; the file moves
    into the album. A picture she cannot caption stays in the inbox for another night."""
    from fish.brain.ask import ask_json
    from fish.messages import data_url, sniff_mime

    inbox = brain.album.folder / "inbox"
    if not inbox.is_dir():
        return 0
    added = 0
    for path in sorted(p for p in inbox.iterdir() if p.suffix.lower() in STICKER_TYPES)[:limit]:
        data = path.read_bytes()
        mime = sniff_mime(data)
        if mime is None:
            continue
        reply = ask_json(brain.llm, "sticker_caption", persona=brain.persona, image=data_url(data),
                         temperature=0.9, max_tokens=200)
        caption = str((reply or {}).get("caption") or "").strip()
        if not caption:
            continue
        tags = reply.get("tags") if isinstance(reply.get("tags"), list) else []
        brain.album.add(data, mime, caption, tags=[str(t) for t in tags][:3], source="inbox", now=now)
        path.unlink()
        added += 1
    return added

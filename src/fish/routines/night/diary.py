"""Night steps 5–5c: her diary and her own life (no diary for days before she met him; the
diary call also rewrites the phase's sentence, slowly); the phase steps a fifth of the way
toward what the day showed (decision 13); about once a month she looks back at herself and
may move a slider a notch."""

from __future__ import annotations

import re
from datetime import date, datetime

from fish.brain import away, moment_line
from fish.cottage import invented_act
from fish.memory import Diary, Pastimes, TraitStore, first_message_at
from fish.routines.night.context import Night, fish_day

SELF_NOTES_PER_NIGHT = 1  # decision 19: her life grows by one thread a night at most
GROWTH_EVERY_DAYS = 30  # layer A looks back about once a month


def strongest(notes: list[tuple[str, int]], n: int) -> list[tuple[str, int]]:
    """Her life grows by at most n threads a night (decision 19): keep the most important."""
    return sorted(notes, key=lambda x: -x[1])[:n]


def write_diary(night: Night) -> None:
    conn, store, day, now, brain = night.conn, night.store, night.day, night.now, night.brain
    first = first_message_at(conn)
    born = fish_day(first) if first else None
    if not (night.thinker and born is not None and day >= born):
        return
    diary = Diary(conn)
    todays = [e for e in night.episodes.recent(20)
              if fish_day(datetime.fromisoformat(e.started)) == day and (e.gist or e.summary)]
    gists = [e.gist or e.summary[:60] for e in reversed(todays)]
    threads = [m.line() for m in store.alive("self")][-5:]
    yesterday = next((t for d, t in diary.recent(1) if d < day.isoformat()), "")
    seen_today = [m.text for m in store.seen_recently(now, 2)
                  if fish_day(datetime.fromisoformat(m.created)) == day]
    leisure = [moment_line(m) for m in Pastimes(conn).moments(night.day_start, night.day_end) if away(m)]
    home: list[str] | None = None
    if brain.cottage is not None:  # what she did at home, meals, food gone off (decision 26)
        try:
            home = brain.cottage.between(night.day_start, night.day_end)
        except ValueError:
            home = []
    prev = night.phases.current()
    text, notes, line = night.thinker.diary(day.isoformat(), night.moods.load().describe(), threads, gists,
                                            yesterday, seen=seen_today, phase_line=prev.line,
                                            tone_word=prev.tone_word, drive_word=prev.drive_word,
                                            leisure=leisure, home=home)
    if not text:
        return
    night.line = line
    diary.write(day.isoformat(), text)
    if home is not None:  # with a room, what she did is in it; her notes keep thoughts
        notes = [n for n in notes if not invented_act(n[0])]
    for note, importance in strongest(notes, SELF_NOTES_PER_NIGHT):
        store.note("self", note, importance=importance, now=now)
    night.report["diary"] = True


def step_phase(night: Night) -> None:
    tone_today, energy_today = night.moods.day_tone(night.day_start, night.day_end)
    focus = [re.sub(r"^[\d\-年月日，, ]+", "", m.text).split("，")[0][:16]
             for m in night.store.alive("self")][-3:]  # short handles, not whole notes
    night.phase = night.phases.update(night.day.isoformat(), tone_today=tone_today,
                                      drive_today=None if energy_today is None else energy_today / 100,
                                      focus=focus, line=night.line)
    night.report["phase"] = {"tone": round(night.phase.tone, 2), "drive": round(night.phase.drive, 2)}


def look_at_herself(night: Night) -> None:
    if not night.thinker:
        return
    day, now = night.day, night.now
    known = night.rel.days_known(now)
    traits = TraitStore(night.conn)
    last = traits.growth_notes(1)
    last_day = date.fromisoformat(last[0].month) if last else None
    if not (known >= GROWTH_EVERY_DAYS and (last_day is None or (day - last_day).days >= GROWTH_EVERY_DAYS)):
        return
    month_diary = [f"{d}：{t}" for d, t in Diary(night.conn).recent(GROWTH_EVERY_DAYS)]
    trend = [f"{p.day}：基调{p.tone_word}，劲头{p.drive_word}" for p in night.phases.history(GROWTH_EVERY_DAYS)][::7]
    note, changes = night.thinker.grow(day.isoformat(), known, month_diary, trend, traits.describe_all())
    applied = traits.apply(changes, now)
    if note:
        traits.add_growth(day.isoformat(), note, applied)
        night.store.add("self", f"{day.isoformat()[:7]} 回头看自己：{note}", importance=6, now=now)
    night.report["growth"] = applied

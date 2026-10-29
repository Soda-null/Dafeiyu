"""Night step 4: every 7 days, or after 5 chats, she looks back: new insights and ways of
getting along, old ones seen again or outdated."""

from __future__ import annotations

from datetime import date, datetime

from fish.routines.night.context import Night, fish_day
from fish.routines.runs import last_run, mark_run

REFLECT_EVERY_DAYS = 7
REFLECT_AFTER_EPISODES = 5


def look_back(night: Night) -> None:
    if not night.thinker:
        return
    conn, store, day, now = night.conn, night.store, night.day, night.now
    last_reflect = last_run(conn, "reflect")
    recent = night.episodes.recent(REFLECT_AFTER_EPISODES * 2)
    # only chats from days after the last reflection: re-reading the same chats is not new
    # evidence, so a rule seen again here has really been seen again (decision 21)
    since = [e for e in recent if not last_reflect
             or fish_day(datetime.fromisoformat(e.started)) > date.fromisoformat(last_reflect)]
    due = (not last_reflect or (day - date.fromisoformat(last_reflect)).days >= REFLECT_EVERY_DAYS
           or len(since) >= REFLECT_AFTER_EPISODES)
    if not (due and since):
        return
    gists = [e.gist or e.summary[:60] for e in reversed(since) if e.gist or e.summary]
    facts = store.profile() + [m for m in store.alive("fact") if m not in store.profile()][:20]
    old = store.alive("insight")  # all of them (at most 20): she may see some are outdated
    old_howto = store.alive("howto")
    # rules written during the chats she now looks back on are that evidence itself: she can
    # neither call them outdated nor see them "again" (memory v3 step 1). The last look back's
    # own rules came before these chats, so these chats are new evidence for them; tonight's
    # merges (created now) are not evidence either way. Before the run time was kept, the first
    # of these chats marks the start.
    at = last_run(conn, "reflect_at")
    start = (datetime.fromisoformat(at) if at else
             min(datetime.fromisoformat(e.started) for e in since))
    newer = {m.id for m in old + old_howto
             if start < datetime.fromisoformat(m.created) < now}
    insights, howtos, outdated, confirms = night.thinker.reflect(gists, facts, old, old_howto, newer=newer)
    for memory_id in outdated:
        store.weaken(memory_id, now)
    for memory_id in confirms:
        store.happened_again(memory_id, now)
    night.report["outdated"] = len(outdated)
    night.report["confirmed"] = len(confirms)
    for text, importance in insights:
        store.note("insight", text, importance=importance, now=now)
    for text, importance in howtos:
        store.note("howto", text, importance=importance, now=now)
    mark_run(conn, "reflect", day.isoformat())
    mark_run(conn, "reflect_at", now.isoformat())  # the time, not the day: see `newer`
    night.report["insights"] = len(insights)
    night.report["howto"] = len(howtos)

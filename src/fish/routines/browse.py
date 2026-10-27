"""Her daily browse (docs/world_design_zh.md §4): once per fish day, from BROWSE_TIME on.

gather headlines -> drop what she opened in the last week -> she picks up to three ->
open them (article text, or a video's blurb and top comments) -> she writes 见闻 and maybe
a new life thread. Two model calls; nothing is downloaded or submitted.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, time
from typing import TYPE_CHECKING

from fish.brain.world import Browser
from fish.memory import EpisodeManager, MemoryStore
from fish.routines.nightly import SELF_NOTES_PER_NIGHT, fish_day, strongest
from fish.routines.runs import claim_run, last_run
from fish.world import Fetch, Item, gather, load_sources, open_item, urllib_fetch

if TYPE_CHECKING:
    from fish.brain.respond import Brain

BROWSE_TIME = time(9, 30)
MAX_ITEMS = 60
SEEN_DAYS = 7


def run_browse(conn: sqlite3.Connection, now: datetime | None = None, *, brain: "Brain",
               sources: list[dict] | None = None, fetch: Fetch = urllib_fetch,
               force: bool = False) -> dict:
    now = now or datetime.now()
    day = fish_day(now).isoformat()
    if last_run(conn, "browse") == day:
        return {"skipped": True, "reason": "done"}
    if not force and now.time() < BROWSE_TIME:
        return {"skipped": True, "reason": "early"}
    if not claim_run(conn, "browse", day):  # another process is browsing this day right now
        return {"skipped": True, "reason": "done"}

    store = MemoryStore(conn)
    items, errors = gather(sources if sources is not None else load_sources(), fetch=fetch)
    opened_before = {m.source for m in store.seen_recently(now, SEEN_DAYS) if m.source}
    items = [i for i in items if i.url not in opened_before][:MAX_ITEMS]
    report: dict = {"skipped": False, "day": day, "items": len(items), "errors": errors,
                    "picked": 0, "seen": 0}
    if items:
        browser = Browser(brain.llm, brain.persona)
        threads = [m.line() for m in store.alive("self")][-5:]
        topics = [e.gist for e in EpisodeManager(conn).recent(3) if e.gist]
        picks = browser.pick(items, day=day, threads=threads, topics=topics)
        opened: list[tuple[Item, str]] = []
        for n in picks:
            item = items[n]
            try:
                text = open_item(item, fetch=fetch)
            except Exception:  # noqa: BLE001 - a page that will not open is just a closed tab
                text = item.summary
            opened.append((item, text))
        seen, self_notes = browser.read(opened)
        for s in seen:
            item = opened[s.index][0]
            store.note("world", s.text, importance=s.importance, valence=s.valence,
                       tags=tuple(s.tags) + (item.source,), source=item.url, now=now)
        for text, importance in strongest(self_notes, SELF_NOTES_PER_NIGHT):
            store.note("self", text, importance=importance, now=now)
        report.update(picked=len(opened), seen=len(seen), self_notes=len(self_notes))
    return report

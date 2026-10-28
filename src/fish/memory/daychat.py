"""Today's chat as she holds it (decision 32): the earlier chats of her day word for word, and
this one whole. Which parts she still has word for word is memory's rule, so it lives here;
how it reads in the prompt is the brain's (prompt.render_day).

Her day starts at 03:30. A very long day over DAY_LIMIT characters keeps only the gist of its
oldest chats; if this chat alone is too long, only the gist of its start. The latest words
are always there as they were said.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fish.memory.episodes import Episode, EpisodeManager
from fish.memory.patterns import DAY_ENDS, day_of
from fish.memory.window import Turn, Window

DAY_LIMIT = 15000  # characters of today's chat kept word for word
TURN_OVERHEAD = 4  # role marker etc. (brain/budget.py counts the same way)
KEEP_LATEST = 10  # turns of this chat that are never cut, however long it runs
NO_GIST = "（聊了些家常）"


@dataclass(frozen=True)
class Block:
    """One earlier chat of today: its turns, and its gist when only that is left."""
    turns: tuple[Turn, ...]
    gist: str | None = None


@dataclass(frozen=True)
class DayChat:
    earlier: tuple[Block, ...] = ()
    current: tuple[Turn, ...] = ()
    cut: bool = False  # the start of this chat is gone; `summary` is what is left of it
    summary: str = ""


def fit(earlier: list[tuple[int | None, list[Turn]]], current: list[Turn], gists: dict[int, str],
        running_summary: str = "", limit: int = DAY_LIMIT) -> DayChat:
    def size(turns) -> int:
        return sum(len(t.text) + TURN_OVERHEAD for t in turns)

    blocks: list[tuple[int | None, list[Turn], str | None]] = [(e, ts, None) for e, ts in earlier if ts]
    total = sum(size(ts) for _, ts, _ in blocks) + size(current)
    for i, (e, ts, _) in enumerate(blocks):
        if total <= limit:
            break
        gist = gists.get(e or -1, "") or NO_GIST
        total += len(gist) + 20 - size(ts)
        blocks[i] = (e, ts, gist)
    cut = False
    if total > limit and current:
        cut = True
        while total > limit and len(current) > KEEP_LATEST:
            total -= size(current[:1])
            current = current[1:]
    return DayChat(tuple(Block(tuple(ts), gist) for _, ts, gist in blocks), tuple(current), cut,
                   running_summary if cut else "")


def day_chat(window: Window, episodes: EpisodeManager, ep: Episode, now: datetime,
             limit: int = DAY_LIMIT) -> DayChat:
    """Everything said since her day began, split into the earlier chats and this one."""
    start = datetime.combine(day_of(now), DAY_ENDS)
    earlier: list[tuple[int | None, list[Turn]]] = []
    for episode_id, turn in window.since(start):
        if episode_id == ep.id:
            continue
        if not earlier or earlier[-1][0] != episode_id:
            earlier.append((episode_id, []))
        earlier[-1][1].append(turn)
    ids = {i for i, _ in earlier}
    gists = {e.id: e.gist for e in episodes.closed() if e.id in ids}
    return fit(earlier, window.episode(ep.id), gists, ep.running_summary, limit)


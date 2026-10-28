"""Leaf through her subscriptions: the news feeds, or Bilibili (what used to be the fixed
09:30 browse, decision 9; now only when she feels like it)."""

from __future__ import annotations

import random

from fish.brain.leisure.base import Activity, Choice, Kit, Material
from fish.world import gather, open_item

SHOWN = 8  # headlines in the menu
MAX_OPEN = 3
SEEN_DAYS = 7  # do not offer what she opened this week


class FeedActivity(Activity):
    def __init__(self, key: str, line: str, kinds: tuple[str, ...], rng: random.Random | None = None) -> None:
        self.key = key
        self.line = line
        self.kinds = kinds
        self.rng = rng or random.Random()

    def offer(self, kit: Kit) -> list[Choice]:
        sources = [s for s in kit.sources if s.get("kind", "rss") in self.kinds]
        if not sources:
            return []
        items, _ = gather(sources, fetch=kit.fetch)
        opened = {m.source for m in kit.store.seen_recently(kit.now, SEEN_DAYS) if m.source}
        items = [i for i in items if i.url not in opened]
        if not items:
            return []
        items = self.rng.sample(items, min(SHOWN, len(items)))
        return [Choice(self.key, self.line, tuple(f"【{i.source}】{i.title}" for i in items),
                       payload={"items": items})]

    def do(self, kit: Kit, choice: Choice, picks: list[int], arg: str) -> Material:
        items = choice.payload["items"]
        chosen = [items[n] for n in picks if 0 <= n < len(items)][:MAX_OPEN] or items[:1]
        opened = []
        for item in chosen:
            try:
                text = open_item(item, fetch=kit.fetch)
            except Exception:  # noqa: BLE001 - a page that will not open is just a closed tab
                text = item.summary
            opened.append((item, text))
        return Material(opened, f"{self.line}，点开了：" + "；".join(i.title[:30] for i, _ in opened))

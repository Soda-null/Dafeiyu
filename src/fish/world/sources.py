"""Her subscriptions (sources.json): gather today's headlines, open one item."""

from __future__ import annotations

import json
from pathlib import Path

from fish.world import bilibili
from fish.world.feeds import fetch_rss
from fish.world.http import Fetch, FetchError, urllib_fetch
from fish.world.items import Item
from fish.world.reader import read_page

SOURCES_PATH = Path(__file__).parent / "sources.json"
PER_SOURCE = 10


def load_sources(path: Path = SOURCES_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def gather(sources: list[dict], *, fetch: Fetch = urllib_fetch,
           per_source: int = PER_SOURCE) -> tuple[list[Item], list[str]]:
    """Headlines from every source; a source that fails is skipped and named in `errors`."""
    items: list[Item] = []
    errors: list[str] = []
    for s in sources:
        try:
            if s.get("kind") == "bilibili":
                items += bilibili.popular(s["url"], s["name"], s.get("flavor", ""), fetch=fetch,
                                          limit=per_source)
            else:
                items += fetch_rss(s["url"], s["name"], s.get("flavor", ""), fetch=fetch,
                                   limit=per_source)
        except Exception as e:  # noqa: BLE001 - one bad feed (blocked, empty, malformed) must not spoil the rest
            errors.append(f"{s.get('name')}: {type(e).__name__}: {str(e)[:80]}")
    return items, errors


def open_item(item: Item, *, fetch: Fetch = urllib_fetch, max_chars: int = 3000) -> str:
    """What she sees when she clicks: the article text, or a video's blurb plus top comments."""
    if bilibili.is_bilibili(item.url):
        lines = [item.summary]
        if item.ref:
            try:
                lines += ["热评：", *[f"- {c}" for c in bilibili.comments(item.ref, fetch=fetch)]]
            except (FetchError, ValueError):
                pass
        return "\n".join(lines)[:max_chars]
    _, text = read_page(item.url, fetch=fetch, max_chars=max_chars * 3)
    head = item.title[:20]
    start = text.find(head) if head else -1
    if start > 0:
        text = text[start:]  # skip the site's header and author boxes
    return text[:max_chars] or item.summary

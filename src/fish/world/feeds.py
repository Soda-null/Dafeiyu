"""RSS 2.0 and Atom feeds -> items, with the standard library only."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET

from fish.world.http import Fetch, urllib_fetch
from fish.world.items import Item

ATOM = "{http://www.w3.org/2005/Atom}"
SUMMARY_CHARS = 200
_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")


def strip_html(text: str, limit: int = SUMMARY_CHARS) -> str:
    text = html.unescape(_TAGS.sub(" ", text or ""))
    text = _SPACES.sub(" ", text).strip()
    return text[:limit]


def _text(el, *names: str) -> str:
    for name in names:
        found = el.find(name)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""


def parse_feed(xml_text: str, source: str, flavor: str, limit: int = 10) -> list[Item]:
    if not xml_text.strip():
        raise ValueError("empty feed")
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    items: list[Item] = []
    for entry in root.iter("item"):  # RSS 2.0
        title = strip_html(_text(entry, "title"), 120)
        link = _text(entry, "link")
        if title and link:
            items.append(Item(title, link, strip_html(_text(entry, "description")), source, flavor))
        if len(items) >= limit:
            return items
    for entry in root.iter(f"{ATOM}entry"):  # Atom
        title = strip_html(_text(entry, f"{ATOM}title"), 120)
        link_el = entry.find(f"{ATOM}link")
        link = (link_el.get("href") if link_el is not None else "") or ""
        if title and link:
            items.append(Item(title, link, strip_html(_text(entry, f"{ATOM}summary", f"{ATOM}content")),
                              source, flavor))
        if len(items) >= limit:
            break
    return items


def fetch_rss(url: str, source: str, flavor: str, *, fetch: Fetch = urllib_fetch,
              limit: int = 10) -> list[Item]:
    return parse_feed(fetch(url, 15.0), source, flavor, limit)

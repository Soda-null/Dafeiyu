"""Chinese Wikisource: old books whose copyright has run out, full text, no key (decision 24).

find_book   a title she thinks of -> the book and its chapters in reading order
read_part   one chapter, a slice at a time (chapters run to 10 000 characters)
"""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass

from fish.world.http import Fetch, FetchError, bot_fetch

API = "https://zh.wikisource.org/w/api.php?format=json&formatversion=2&redirects=1&"
PAGE_URL = "https://zh.wikisource.org/wiki/{title}"
HREF = re.compile(r'href="/wiki/([^"#?]+)"')
NAV = re.compile(r"目錄|目录|上一|下一")


@dataclass(frozen=True)
class Book:
    title: str
    chapters: tuple[str, ...]  # page titles; a one-page work is its own only chapter
    url: str


def page_url(title: str) -> str:
    return PAGE_URL.format(title=urllib.parse.quote(title))


def _get(fetch: Fetch, query: str) -> dict:
    return json.loads(fetch(API + query, 15.0))


def chapters_of(title: str, *, fetch: Fetch = bot_fetch) -> tuple[str, tuple[str, ...]]:
    """(canonical title, its subpages in the order the index page links them)."""
    page = _get(fetch, "action=parse&prop=text&page=" + urllib.parse.quote(title))["parse"]
    canonical = page["title"]
    seen: list[str] = []
    for href in HREF.findall(page.get("text") or ""):
        t = urllib.parse.unquote(href).replace("_", " ")
        if t.startswith(canonical + "/") and t not in seen:
            seen.append(t)
    return canonical, tuple(seen)


def find_book(name: str, *, fetch: Fetch = bot_fetch) -> Book | None:
    name = name.strip().strip("《》").strip()[:40]
    if not name:
        return None
    try:
        # intitle: so a book she has in mind is not answered with some page that mentions it
        hits = _get(fetch, "action=query&list=search&srnamespace=0&srlimit=3&srsearch="
                    + urllib.parse.quote("intitle:" + name))
        results = [h["title"] for h in (hits.get("query") or {}).get("search") or []]
        if not results:
            return None
        title, chapters = chapters_of(results[0].split("/")[0], fetch=fetch)
    except (FetchError, ValueError, KeyError, TypeError):
        return None
    return Book(title, chapters or (title,), page_url(title))


def read_part(chapter: str, offset: int = 0, *, fetch: Fetch = bot_fetch,
              max_chars: int = 3000) -> tuple[str, int]:
    """(text from `offset`, the chapter's full length). Raises FetchError when it will not load."""
    try:
        data = _get(fetch, "action=query&prop=extracts&explaintext=1&titles=" + urllib.parse.quote(chapter))
        text = (data["query"]["pages"][0].get("extract") or "").strip()
    except (ValueError, KeyError, TypeError, IndexError) as e:
        raise FetchError(f"{chapter}: {e}") from e
    lines = text.split("\n")
    while lines and len(lines[0]) < 20 and NAV.search(lines[0]):
        lines.pop(0)  # "回目录　下一回" and the like
    text = "\n".join(lines).strip()
    return text[offset:offset + max_chars], len(text)

"""Look something up: Chinese Wikipedia first. A general search engine (needs a key)
can plug in behind the same Searcher protocol later."""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from typing import Protocol

from fish.world.http import Fetch, FetchError, urllib_fetch

SEARCH_URL = ("https://zh.wikipedia.org/w/api.php?action=query&list=search&format=json"
              "&srlimit=1&srsearch={q}")
SUMMARY_URL = "https://zh.wikipedia.org/api/rest_v1/page/summary/{title}"
EXTRACT_CHARS = 600


@dataclass(frozen=True)
class Lookup:
    query: str
    title: str
    text: str
    url: str


class Searcher(Protocol):
    name: str

    def lookup(self, query: str) -> Lookup | None: ...


class WikiSearcher:
    name = "维基百科"

    def __init__(self, fetch: Fetch = urllib_fetch) -> None:
        self.fetch = fetch

    def lookup(self, query: str) -> Lookup | None:
        query = query.strip()[:60]
        if not query:
            return None
        try:
            hits = json.loads(self.fetch(SEARCH_URL.format(q=urllib.parse.quote(query)), 10.0))
            results = ((hits.get("query") or {}).get("search")) or []
            if not results:
                return None
            title = results[0]["title"]
            page = json.loads(self.fetch(SUMMARY_URL.format(title=urllib.parse.quote(title)), 10.0))
        except (FetchError, ValueError, KeyError, TypeError):
            return None
        text = (page.get("extract") or "").strip()
        if not text:
            return None
        url = ((page.get("content_urls") or {}).get("desktop") or {}).get("page") \
            or f"https://zh.wikipedia.org/wiki/{urllib.parse.quote(title)}"
        return Lookup(query, title, text[:EXTRACT_CHARS], url)

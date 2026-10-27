"""A web page -> the readable text, capped. No links followed, nothing submitted."""

from __future__ import annotations

import re
from html.parser import HTMLParser

from fish.world.http import Fetch, urllib_fetch

MAX_CHARS = 3000
SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "iframe"}
BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article",
         "blockquote", "pre"}
_BLANKS = re.compile(r"[ \t　]+")
_LINES = re.compile(r"\n{3,}")


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip += 1
        elif tag in BLOCK:
            self.parts.append("\n")
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in SKIP and self.skip:
            self.skip -= 1
        elif tag in BLOCK:
            self.parts.append("\n")
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def html_to_text(page: str, max_chars: int = MAX_CHARS) -> tuple[str, str]:
    """Returns (title, text)."""
    p = _Text()
    p.feed(page)
    text = "".join(p.parts)
    text = _BLANKS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = _LINES.sub("\n\n", text).strip()
    return p.title.strip()[:120], text[:max_chars]


def read_page(url: str, *, fetch: Fetch = urllib_fetch, max_chars: int = MAX_CHARS) -> tuple[str, str]:
    return html_to_text(fetch(url, 15.0), max_chars)

"""One small fetch function, swappable in tests. Text only; she never downloads files."""

from __future__ import annotations

import socket
import urllib.error
import urllib.request
from typing import Callable

USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"
              " Chrome/124.0 Safari/537.36")
MAX_BYTES = 1_500_000

Fetch = Callable[[str, float], str]  # (url, timeout) -> body text


class FetchError(RuntimeError):
    pass


FetchBytes = Callable[[str, float], bytes]  # (url, timeout) -> raw body (map tiles)
FetchPost = Callable[[str, dict[str, str], float], str]  # (url, form fields, timeout) -> body text


def urllib_fetch_bytes(url: str, timeout: float = 15.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Dafeiyu/0.1 (personal AI friend; low volume)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(MAX_BYTES)
    except (urllib.error.URLError, socket.timeout, TimeoutError, ValueError) as e:
        raise FetchError(f"{url}: {e}") from e


def urllib_post(url: str, form: dict[str, str], timeout: float = 40.0) -> str:
    import urllib.parse

    req = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(),
                                 headers={"User-Agent": "Dafeiyu/0.1 (personal AI friend; low volume)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(MAX_BYTES).decode("utf-8", "replace")
    except (urllib.error.URLError, socket.timeout, TimeoutError, ValueError) as e:
        raise FetchError(f"{url}: {e}") from e


def urllib_fetch(url: str, timeout: float = 15.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(MAX_BYTES)
            charset = resp.headers.get_content_charset() or "utf-8"
    except (urllib.error.URLError, socket.timeout, TimeoutError, ValueError) as e:
        raise FetchError(f"{url}: {e}") from e
    try:
        return raw.decode(charset, "replace")
    except LookupError:
        return raw.decode("utf-8", "replace")

"""Bilibili's public endpoints (no login): popular videos, a zone ranking, top comments.

She cannot watch a video; what she "watches" is the title, the uploader's blurb and the
top comments, which is where the fun is anyway.
"""

from __future__ import annotations

import json

from fish.world.feeds import strip_html
from fish.world.http import Fetch, urllib_fetch
from fish.world.items import Item

COMMENTS_URL = "https://api.bilibili.com/x/v2/reply?type=1&oid={aid}&sort=1&ps={limit}"
VIDEO_URL = "https://www.bilibili.com/video/{bvid}"


def is_bilibili(url: str) -> bool:
    return "bilibili.com" in url


def _items(payload: str, source: str, flavor: str, limit: int) -> list[Item]:
    data = json.loads(payload)
    if data.get("code") != 0:
        raise ValueError(f"bilibili code {data.get('code')}: {data.get('message')}")
    items: list[Item] = []
    for v in (data.get("data") or {}).get("list") or []:
        bvid = v.get("bvid")
        if not bvid:
            continue
        owner = (v.get("owner") or {}).get("name", "")
        stat = v.get("stat") or {}
        blurb = strip_html(v.get("desc", ""), 160)
        summary = f"UP主 {owner}，分区 {v.get('tname', '')}，播放 {stat.get('view', 0)}。{blurb}"
        items.append(Item(strip_html(v.get("title", ""), 120), VIDEO_URL.format(bvid=bvid),
                          summary, source, flavor, ref=str(v.get("aid", ""))))
        if len(items) >= limit:
            break
    return items


def popular(url: str, source: str, flavor: str, *, fetch: Fetch = urllib_fetch,
            limit: int = 10) -> list[Item]:
    return _items(fetch(url, 15.0), source, flavor, limit)


ranking = popular  # same response shape


def comments(aid: str, *, fetch: Fetch = urllib_fetch, limit: int = 5) -> list[str]:
    data = json.loads(fetch(COMMENTS_URL.format(aid=aid, limit=limit), 15.0))
    if data.get("code") != 0:
        return []
    out = []
    for r in (data.get("data") or {}).get("replies") or []:
        text = strip_html((r.get("content") or {}).get("message", ""), 120)
        if text:
            out.append(text)
    return out[:limit]

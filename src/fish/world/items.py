"""What every source yields: a headline she might click on."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    title: str
    url: str
    summary: str  # a line or two; already plain text
    source: str  # the subscription's name, e.g. 少数派
    flavor: str  # what kind of place it is, e.g. 刷视频
    ref: str = ""  # a source-specific id (Bilibili aid) used to open the item

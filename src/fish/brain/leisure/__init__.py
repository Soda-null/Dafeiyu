"""Her free time (decision 24, docs/free_time_design_zh.md): "you may", never "you must".

To give her something new to do: write a file here with an `Activity` subclass (see
`base.py`: `offer` lays out menu lines, `do` fetches what she looks at), then add one line
to `default_activities` below. The free-moment loop, her choice, what she writes down and
the log need no change.
"""

from __future__ import annotations

import random

from fish.brain.leisure.base import Activity, Choice, Kit, Material
from fish.brain.leisure.book import BookActivity
from fish.brain.leisure.curious import CuriousActivity
from fish.brain.leisure.feeds import FeedActivity
from fish.brain.leisure.free import NOTHING, Leisure, LeisurePolicy, moment_line, pastimes_line, render_menu


def default_activities(rng: random.Random | None = None) -> list[Activity]:
    return [
        FeedActivity("news", "翻翻新闻", ("rss",), rng),
        FeedActivity("bilibili", "刷刷 B 站、听听歌", ("bilibili",), rng),
        BookActivity(),
        CuriousActivity(),
    ]


__all__ = ["NOTHING", "Activity", "BookActivity", "Choice", "CuriousActivity", "FeedActivity", "Kit",
           "Leisure", "LeisurePolicy", "Material", "default_activities", "moment_line", "pastimes_line",
           "render_menu"]

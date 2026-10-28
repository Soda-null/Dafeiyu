"""Recall by time (memory v2 step 5): "what did I eat last night" shares no words with
"he had malatang with his roommate on 2027-01-06", but a person finds it by thinking of
last night first. When the cue names a time, memories from that time count as relevant.

No model. `window` reads the time words of a cue into a date range; a memory's days are the
dates written in it (notes carry them, "他2027-01-06晚上……") and the day it was written.
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, timedelta

from fish.memory.longterm import Memory

# How much being from the named time counts, by how many days the cue names: "last night" is
# one day and points hard; "last January" is a month and only nudges. Words that also match
# add on top, so the right memory from that time outranks the rest of that time.
SPAN_HIT = ((1, 0.6), (3, 0.5), (7, 0.45), (31, 0.25))
YEAR_HIT = 0.1
NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
       "十一": 11, "十二": 12}
WEEKDAY = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
DATE_IN_TEXT = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
N = r"(\d{1,2}|十[一二]?|[一二两三四五六七八九十])"
WEEK = r"(?:周|星期|礼拜)"
LAST_WEEK = r"(?:上周|上个?星期|上个?礼拜)"
THIS_WEEK = r"(?:这周|本周|这个?星期|这个?礼拜)"
HABIT = re.compile(r"一般|每[周天个次回]|经常|总是|老是|平时")  # "what do I usually eat on Fridays" names no one day


def _n(s: str) -> int:
    return int(s) if s.isdigit() else NUM[s]


def _month(year: int, month: int, part: str = "") -> tuple[date, date]:
    last = monthrange(year, month)[1]
    lo, hi = {"初": (1, 10), "中": (11, 20), "底": (21, last), "末": (21, last)}.get(part, (1, last))
    return date(year, month, lo), date(year, month, hi)


def window(cue: str, now: datetime) -> tuple[date, date] | None:
    """The days a cue points at, or None when it names no time."""
    if HABIT.search(cue):
        return None
    today = now.date()
    monday = today - timedelta(days=today.weekday())
    if m := re.search(rf"{LAST_WEEK}([一二三四五六日天])", cue):
        d = monday - timedelta(days=7) + timedelta(days=WEEKDAY[m.group(1)])
        return d, d
    if re.search(LAST_WEEK, cue):
        return monday - timedelta(days=7), monday - timedelta(days=1)
    if re.search(THIS_WEEK, cue):
        return monday, today
    if "大前天" in cue:
        d = today - timedelta(days=3)
        return d, d
    if re.search(r"前天|前晚", cue):
        d = today - timedelta(days=2)
        return d, d
    if re.search(r"昨[天晚儿日早]", cue):
        d = today - timedelta(days=1)
        return d, d
    if m := re.search(rf"{N}天前", cue):
        d = today - timedelta(days=_n(m.group(1)))
        return d - timedelta(days=1), d + timedelta(days=1)
    if re.search(r"前几天|前两天|这几天|最近几天", cue):
        return today - timedelta(days=7), today
    if m := re.search(rf"{N}月{N}[号日]", cue):
        month, day = _n(m.group(1)), _n(m.group(2))
        year = today.year - (1 if "去年" in cue or (month, day) > (today.month, today.day) else 0)
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        return d, d
    if m := re.search(rf"{N}月(?:份)?([初中底末])?", cue):
        month = _n(m.group(1))
        if 1 <= month <= 12:
            year = today.year - (1 if "去年" in cue or month > today.month else 0)
            return _month(year, month, m.group(2) or "")
    if "上个月" in cue:
        first = today.replace(day=1) - timedelta(days=1)
        return _month(first.year, first.month)
    if re.search(r"这个月|本月", cue):
        return today.replace(day=1), today
    if "去年" in cue:
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if re.search(r"今[天晚早儿]", cue):
        return today, today
    if m := re.search(rf"{WEEK}([一二三四五六日天])", cue):
        back = (today.weekday() - WEEKDAY[m.group(1)]) % 7 or 7
        d = today - timedelta(days=back)
        return d, d
    return None


def time_hit(span_days: int) -> float:
    return next((hit for days, hit in SPAN_HIT if span_days <= days), YEAR_HIT)


def days_of(memory: Memory) -> set[date]:
    """The days a memory is about: the dates written in it, and the day it was written."""
    days = set()
    for y, mo, d in DATE_IN_TEXT.findall(memory.text):
        try:
            days.add(date(int(y), int(mo), int(d)))
        except ValueError:
            continue
    if memory.created:
        days.add(datetime.fromisoformat(memory.created).date())
    return days


class TimeCued:
    """Wraps another Embedder: a memory from the time the cue names is relevant even when
    no word matches. Cues without a time behave exactly as before."""

    def __init__(self, base, now: datetime) -> None:
        self.base = base
        self.now = now
        self._cue = None
        self._window: tuple[date, date] | None = None

    def relevance(self, cue: str, memory: Memory) -> float:
        rel = self.base.relevance(cue, memory)
        if cue != self._cue:
            self._cue, self._window = cue, window(cue, self.now)
        if self._window is None:
            return rel
        lo, hi = self._window
        if any(lo <= d <= hi for d in days_of(memory)):
            hit = time_hit((hi - lo).days + 1)
            return rel + hit * (1 - rel)
        return rel

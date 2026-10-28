"""Recall by time (memory v2 step 5): "what did I eat last night" shares no words with
"he had malatang with his roommate on 2027-01-06", but a person finds it by thinking of
last night first. When the cue names a time, memories from that time count as relevant.

No model. `window` reads the time words of a cue into a date range; a memory's days are the
dates written in it (notes carry them, "他2027-01-06晚上……") and the day it happened
(`happened_on`, memory v3), or for older rows the day it was written.

Memory v3 step 3 adds the other direction, for writing: `day_of` reads the one day a note
(or his line) names, past or future ("下下周二"); `fix_weekday` makes a date agree with the
weekday written next to it; `spoken` says a day the way a person would ("上周三 1月6日").
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # longterm imports this module to date its notes
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


# --- writing: the day a note is about (memory v3 §B1, §B2 D5) ----------------------------

CN_DIGITS = "零一二三四五六七八九"
WEEKDAYS_CN = "一二三四五六日"
ISO_DATE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
CN_DATE = re.compile(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})([日号])")
WEEKDAY_WORD = re.compile(r"(?:周|星期|礼拜)([一二三四五六日天])")
# A birthday or an anniversary written without a year is a day of every year, not the day
# the note is about ("他的生日是3月14日" is said on 1/5 and about 1/5).
ANNUAL = re.compile(r"生日|纪念日|周年")
_RELATIVE = re.compile(
    r"大前天|(?<![以之从提])前[天晚]|昨[天晚儿日早]|今[天晚早儿]|明[天晚早儿]|大后天|(?<![以之然最])后天"
    rf"|(上上|下下|上|下|这|本){WEEK}([一二三四五六日天])"
    rf"|{N}天(?:前|后|以后|之后)"
)
_FIXED = {"大前天": -3, "前天": -2, "前晚": -2, "后天": 2, "大后天": 3}


def _nearest(month: int, day: int, today: date) -> date | None:
    """A month and day without a year: the one closest to today (a plan in January said in
    December is next year; a dinner on 12/30 told on 1/2 was last year)."""
    best = None
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if best is None or abs((d - today).days) < abs((best - today).days):
            best = d
    return best


def dates_in(text: str, today: date) -> list[tuple[int, int, date, str]]:
    """The dates written in a text, in order: (start, end, day, how it was written)."""
    found = []
    for m in ISO_DATE.finditer(text):
        try:
            found.append((m.start(), m.end(), date(int(m[1]), int(m[2]), int(m[3])), "iso"))
        except ValueError:
            continue
    taken = [(a, b) for a, b, _, _ in found]
    for m in CN_DATE.finditer(text):
        if any(a <= m.start() < b for a, b in taken):
            continue
        if m[1]:
            try:
                d = date(int(m[1]), int(m[2]), int(m[3]))
            except ValueError:
                continue
        elif (d := _nearest(int(m[2]), int(m[3]), today)) is None:
            continue
        found.append((m.start(), m.end(), d, "cn" + m[4] + ("y" if m[1] else "")))
    return sorted(found)


def _relative_days(text: str, today: date) -> set[date]:
    monday = today - timedelta(days=today.weekday())
    days = set()
    for m in _RELATIVE.finditer(text):
        word = m.group(0)
        if word in _FIXED:
            days.add(today + timedelta(days=_FIXED[word]))
        elif word[0] in "昨今明":
            days.add(today + timedelta(days="昨今明".index(word[0]) - 1))
        elif m.group(1):
            week = {"上上": -2, "上": -1, "这": 0, "本": 0, "下": 1, "下下": 2}[m.group(1)]
            days.add(monday + timedelta(days=7 * week + WEEKDAY[m.group(2)]))
        else:
            n = _n(m.group(3))
            days.add(today + timedelta(days=-n if word.endswith("前") else n))
    return days


def day_of(text: str, now: datetime, said: str = "") -> date | None:
    """The day a note is about: a date written in it; else the one day its time words name
    ("他明天面试", read at `now`); else the same from his line (`said`, the message the note
    came from). None when nothing names exactly one day: the caller uses the message's day.
    A bare "周五" names no day (last Friday or the coming one) and neither do "上周", "最近"."""
    today = now.date()
    for words in (text, said):
        if not words:
            continue
        annual = bool(ANNUAL.search(words))
        for _, _, d, form in dates_in(words, today):
            if not (annual and form.startswith("cn") and not form.endswith("y")):
                return d
        days = _relative_days(words, today)
        if len(days) == 1:
            return days.pop()
        if days:
            return None  # "明天面试，今天先复习": more than one day, so not this one
    return None


def _written(d: date, form: str) -> str:
    if form == "iso":
        return d.isoformat()
    return (f"{d.year}年" if form.endswith("y") else "") + f"{d.month}月{d.day}{form[2]}"


def fix_weekday(text: str, today: date) -> str:
    """A date and the weekday written next to it disagree ("2027-01-24周六", but 1/24 is a
    Sunday): the weekday wins, the date moves to the nearest day that is that weekday
    (at most 3 days away). People say "这周六" and the model works out the date wrong."""
    out = text
    for start, end, d, form in reversed(dates_in(text, today)):
        after = re.match(rf"\s*[（(]?\s*{WEEKDAY_WORD.pattern}", text[end:])
        before = re.search(rf"{WEEKDAY_WORD.pattern}\s*[（(]?\s*$", text[:start])
        word = after or before
        if word is None:
            continue
        shift = (WEEKDAY[word.group(1)] - d.weekday()) % 7
        if shift == 0:
            continue
        right = d + timedelta(days=shift if shift <= 3 else shift - 7)
        out = out[:start] + _written(right, form) + out[end:]
    return out


def _cn(n: int) -> str:
    return "两" if n == 2 else CN_DIGITS[n] if n < 10 else "十" if n == 10 else str(n)


def spoken(d: date, today: date) -> str:
    """A day as a person says it, worked out here so the model does not count: "昨天 1月19日",
    "上周三 1月13日", "下下周二 2月2日"; further away "1月6日，三周前", "2026年3月14日，一年前"."""
    md = f"{d.month}月{d.day}日"
    delta = (d - today).days
    near = {-2: "前天", -1: "昨天", 0: "今天", 1: "明天", 2: "后天"}
    if delta in near:
        return f"{near[delta]} {md}"
    weeks = (d - timedelta(days=d.weekday()) - (today - timedelta(days=today.weekday()))).days // 7
    if -2 <= weeks <= 2:
        return f"{('上上', '上', '这', '下', '下下')[weeks + 2]}周{WEEKDAYS_CN[d.weekday()]} {md}"
    if d.year != today.year:
        md = f"{d.year}年{md}"
    if delta > 0:
        return f"{md}，{delta}天后"
    days = -delta
    if days < 31:
        return f"{md}，{_cn(days // 7)}周前"
    if days < 365:
        return f"{md}，{_cn(max(1, round(days / 30.4)))}个月前"
    return f"{md}，{_cn(days // 365)}年前"



def time_hit(span_days: int) -> float:
    return next((hit for days, hit in SPAN_HIT if span_days <= days), YEAR_HIT)


def days_of(memory: Memory) -> set[date]:
    """The days a memory is about: the dates written in it, and the day it happened. Rows
    from before memory v3 have no `happened_on`; for them it is the day it was written,
    which for a note written when a chat closed at night was the next day."""
    days = set()
    for y, mo, d in DATE_IN_TEXT.findall(memory.text):
        try:
            days.add(date(int(y), int(mo), int(d)))
        except ValueError:
            continue
    if memory.happened_on:
        days.add(date.fromisoformat(memory.happened_on))
    elif memory.created:
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

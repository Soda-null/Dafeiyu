"""The "today" section of the chat prompt (memory v3 §B3): what day it is, worked out by code
so the model never counts days itself.

The model wrote "2027-01-24 周六" when that Saturday was the 23rd, and saw "现在是 2027-03-14"
next to "他的生日是3月14日" without noticing it was his birthday. So the code says it:

- a date table: yesterday, the day before, every day of this week and next, 下下周二;
- his birthday (or an anniversary on her card) today or within 3 days;
- what he said would happen today or tomorrow (`happened_on`, said before the day);
- a line for a weekday pattern the night counted, if today is its day (memory v3 step 6);
- when he usually comes, if the caller has that line (memory v3 step 6).

No model, no database: respond.py hands in what it already picked.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from fish.memory.longterm import Memory
from fish.memory.when import WEEKDAYS_CN, spoken

SOON_DAYS = 3  # a birthday this many days ahead is mentioned
PLANNED_SHOWN = 3
_CN_MONTH = r"(\d{1,2}|十[一二]?|[一二三四五六七八九十])"
_CN_DAY = r"(\d{1,2}|[二三]?十[一二三四五六七八九]?|[一二三四五六七八九])"
# "3月14日", "3月14号", "三月十四", "2005-03-14": a day of the year on a birthday fact.
MONTH_DAY = re.compile(rf"\d{{4}}-(\d{{1,2}})-(\d{{1,2}})|{_CN_MONTH}月{_CN_DAY}")
YEARLY = re.compile(r"生日|纪念日|周年")
_STOP = re.compile(r"[，。,；;！!？?、：:]")


def _num(s: str) -> int:
    """Arabic or Chinese numerals up to 31 ("十四", "二十三")."""
    if s.isdigit():
        return int(s)
    digits = "一二三四五六七八九"
    if "十" not in s:
        return digits.index(s) + 1
    tens, _, ones = s.partition("十")
    return (digits.index(tens) + 1 if tens else 1) * 10 + (digits.index(ones) + 1 if ones else 0)


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def calendar(today: date) -> str:
    """The days she may need to name, each with its date, so "这周六" is never worked out wrong."""
    monday = today - timedelta(days=today.weekday())

    def week(start: date) -> str:
        return " ".join(f"{WEEKDAYS_CN[i]}{_md(start + timedelta(days=i))}" for i in range(7))

    y, b = today - timedelta(days=1), today - timedelta(days=2)
    return (f"昨天 {_md(y)} 周{WEEKDAYS_CN[y.weekday()]}，前天 {_md(b)} 周{WEEKDAYS_CN[b.weekday()]}。"
            f"这周（一到日）：{week(monday)}。下周：{week(monday + timedelta(days=7))}。"
            f"下下周二 {_md(monday + timedelta(days=15))}。")


def _next(month: int, day: int, today: date) -> date | None:
    """The next time this day of the year comes, today included (Feb 29 counts as Feb 28)."""
    for year in (today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            d = date(year, month, 28) if (month, day) == (2, 29) else None
        if d is not None and d >= today:
            return d
    return None


def yearly(card: list[Memory], today: date, him: str = "他") -> list[str]:
    """His birthday today or soon, or another day of the year written on her card."""
    lines = []
    for m in card:
        word = YEARLY.search(m.text)
        hit = MONTH_DAY.search(m.text) if word else None
        if hit is None:
            continue
        month, day = (int(hit[1]), int(hit[2])) if hit[1] else (_num(hit[3]), _num(hit[4]))
        when = _next(month, day, today)
        if when is None or (when - today).days > SOON_DAYS:
            continue
        left, md = (when - today).days, f"{month}月{day}日"
        if word.group(0) == "生日":  # whose: what comes before 生日 ("他的", "他妹妹小雨的")
            whose = _STOP.split(m.text[:word.start()])[-1].removesuffix("的").strip()
            what = f"{whose if 0 < len(whose) <= 6 else him}生日"
            lines.append(f"今天是{what}（{md}）！" if left == 0 else f"再过 {left} 天是{what}（{md}）。")
        else:
            lines.append(f"今天就是这个日子（{md}）：{m.text}" if left == 0
                         else f"再过 {left} 天就是这个日子（{md}）：{m.text}")
    return lines


def planned(memories: list[Memory], today: date) -> list[str]:
    """What he said would happen today or tomorrow, with when he said it, since its words
    may still say "明天" from the day he said it."""
    lines = []
    for m in memories[:PLANNED_SHOWN]:
        label = "今天" if m.happened_on == today.isoformat() else "明天"
        lines.append(f"{label}：{m.text}（{spoken(date.fromisoformat(m.created[:10]), today)}说的）")
    return lines


def pattern_lines(patterns: list[dict], today: date) -> list[str]:
    """A weekday pattern counted at night (memory v3 step 6), on its own weekday only.
    Each pattern: {"weekday": 0-6, "phrase", "weeks", "sample", "status": active | lapsed}."""
    lines = []
    for p in patterns:
        if p.get("status") != "active" or p.get("weekday") != today.weekday():
            continue
        day = f"周{WEEKDAYS_CN[today.weekday()]}"
        line = f"今天{day}：前几个{day}他都说到「{p['phrase']}」（{p.get('weeks', 3)} 个{day}）"
        lines.append(line + (f"，比如「{p['sample']}」。" if p.get("sample") else "。"))
    return lines


def section(now: datetime, card: list[Memory], plans: list[Memory], *, patterns: list[dict] = (),
            arrival: str = "", him: str = "他") -> str:
    """The whole section. card: her card (the birthday is on it); plans: what the store says is
    planned for today and tomorrow; arrival: the "when he usually comes" line, if any."""
    today = now.date()
    lines = [calendar(today), *yearly(card, today, him), *planned(plans, today),
             *pattern_lines(list(patterns), today)]
    if arrival:
        lines.append(arrival)
    return "\n".join(lines)

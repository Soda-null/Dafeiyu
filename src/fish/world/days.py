"""What day it is (decision 24): solar terms, China's public holidays and make-up workdays.

Solar terms come from the usual 21st-century formula (right to within a day). Holidays come
from the public holiday-cn table (published each year after the State Council's notice, no
key), cached as data/home/holidays-YYYY.json. Without the cache she just knows the weekday.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from fish.world.http import Fetch, FetchError, urllib_fetch

HOLIDAY_URL = "https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json"
REFRESH_DAYS = 7
COUNTDOWN_DAYS = 30

# (name, month, C) for [Y*D + C] - L, Y = year % 100 (21st century).
TERMS = (("小寒", 1, 5.4055), ("大寒", 1, 20.12), ("立春", 2, 3.87), ("雨水", 2, 18.73),
         ("惊蛰", 3, 5.63), ("春分", 3, 20.646), ("清明", 4, 4.81), ("谷雨", 4, 20.1),
         ("立夏", 5, 5.52), ("小满", 5, 21.04), ("芒种", 6, 5.678), ("夏至", 6, 21.37),
         ("小暑", 7, 7.108), ("大暑", 7, 22.83), ("立秋", 8, 7.5), ("处暑", 8, 23.13),
         ("白露", 9, 7.646), ("秋分", 9, 23.042), ("寒露", 10, 8.318), ("霜降", 10, 23.438),
         ("立冬", 11, 7.438), ("小雪", 11, 22.36), ("大雪", 12, 7.18), ("冬至", 12, 21.94))
D = 0.2422


def solar_term(d: date) -> str | None:
    y = d.year % 100
    for name, month, c in TERMS:
        if month != d.month:
            continue
        leap = (y - 1) // 4 if month <= 2 else y // 4  # Jan/Feb terms count leap days before this year
        if int(y * D + c) - leap == d.day:
            return name
    return None


def holiday_path(folder: Path, year: int) -> Path:
    return folder / f"holidays-{year}.json"


def load_holidays(folder: Path, year: int) -> dict[str, tuple[str, bool]]:
    """{YYYY-MM-DD: (holiday name, is a day off)}; a make-up workday is (name, False)."""
    p = holiday_path(folder, year)
    if not p.exists():
        return {}
    try:
        days = json.loads(p.read_text(encoding="utf-8")).get("days") or []
        return {d["date"]: (str(d["name"]), bool(d["isOffDay"])) for d in days}
    except (ValueError, KeyError, TypeError, AttributeError):
        return {}


def refresh_holidays(folder: Path, today: date, *, fetch: Fetch = urllib_fetch) -> list[int]:
    """Fetch this year's table (and next year's from November) unless cached this week.
    Returns the years fetched; network trouble just leaves the old cache."""
    folder.mkdir(parents=True, exist_ok=True)
    fetched = []
    for year in (today.year, today.year + 1) if today.month >= 11 else (today.year,):
        p = holiday_path(folder, year)
        if p.exists() and datetime.now().timestamp() - p.stat().st_mtime < REFRESH_DAYS * 86400:
            continue
        try:
            body = fetch(HOLIDAY_URL.format(year=year), 15.0)
            if json.loads(body).get("days"):
                p.write_text(body, encoding="utf-8")
                fetched.append(year)
        except (FetchError, ValueError, AttributeError):
            continue
    return fetched


def day_line(d: date, folder: Path | None = None) -> str:
    """One plain sentence about today, empty when there is nothing to say."""
    parts = []
    term = solar_term(d)
    if term:
        parts.append(f"今天{term}")
    table: dict[str, tuple[str, bool]] = {}
    if folder is not None:
        table = {**load_holidays(folder, d.year), **load_holidays(folder, d.year + 1)}
    today = table.get(d.isoformat())
    if today:
        name, off = today
        parts.append(f"今天{name}放假" if off else f"今天是{name}的调休，要上班")
    else:
        for n in range(1, COUNTDOWN_DAYS + 1):
            hit = table.get((d + timedelta(days=n)).isoformat())
            if hit and hit[1]:
                parts.append(f"离{hit[0]}放假还有 {n} 天")
                break
    return "，".join(parts) + "。" if parts else ""

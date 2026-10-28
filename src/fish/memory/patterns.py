"""What he does on a weekday, and when he usually comes (memory v3 §B6), counted by code.

He said "今天食堂有糖醋排骨，爽" six Fridays running and she never noticed: no note was ever
written, and a model reading summaries cannot count weekdays. So the night counts them here,
from his own lines, with no model:

- weekday patterns: a few words he says on one weekday: in four or more different weeks, at
  least three times in four on that weekday, on three in four of those weekdays he talked and
  four of them in a row, at one time of day. Stored as the `patterns` key of the relationship
  ledger, each `active`, or `lapsed` once he came on that weekday three times running without
  saying it. The design asked for three weeks; on made-up noise (everyday lines of both
  scripted friends on random days) that found a habit for most friends, these rules for 1-2 in
  100 (docs/memory_v3_zh.md §12);
- when he usually comes: the clock time of his first message each day, the last 14 days he
  talked against the 14 before, worked out on every turn (not stored).

Only shown to her on the weekday itself, or when he says 一般/平时/每周 (today.py). Never an
insight she "confirmed": she was told, she did not see it herself.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta

from fish.memory.scrub import secret
from fish.memory.when import WEEKDAYS_CN, spoken

DAY_ENDS = time(3, 30)  # her day ends here (routines/nightly.py NIGHT_BOUNDARY)
WINDOW_DAYS = 56
MIN_WEEKS = 4
SHARE = 0.75  # of the days a phrase was said, this many on its weekday
COVER = 0.75  # of his talked days on that weekday, from its first to its last, this many say it
STREAK = 4  # and this many of them in a row; and at one time of day, SHARE of them
LAPSE_AFTER = 3  # his talked days on that weekday in a row without it
KEPT = 10
SHOWN = 3
MIN_LEN, MAX_LEN = 2, 6
# A question is not news about his day; a line about another day is not about this one.
QUESTION = re.compile(r"[？?]|吗|啥|谁|记得|来着")
OTHER_DAY = re.compile(r"明天|昨天|昨晚|前天|后天|明早|明晚|上周|下周|上个?星期|下个?星期|上个?礼拜|下个?礼拜")
# Words that are about every day, not one: cut out before the phrases are taken.
GENERIC = re.compile(r"今天|今晚|今早|早上|上午|中午|下午|晚上|周[一二三四五六日天末]|星期.|礼拜.|一下|还是|"
                     r"就是|然后|好像|觉得|有点|回来|真的|一般|平时|每周")
BREAK = re.compile(r"[我你的了是在有和跟还又也都就着吧啊呢吗呀哦嗯哈呗啦嘛]")  # not 他 (吉他) or 过 (过敏)
CJK = re.compile(r"[一-鿿]+")
USUALLY = re.compile(r"一般|平时|平常|每个?(?:周|星期|礼拜)")  # he asks about a habit
# (from hour, to hour, word) for the time of day; 深夜 wraps past midnight
BANDS = ((5, 11, "早上"), (11, 14, "中午"), (14, 18, "下午"), (18, 23, "晚上"))
# when he comes: coarser, so 8 点 and 12 点 count as the same habit
ARRIVAL_BANDS = ((5, 18, "白天"), (18, 23, "晚上"))
ARRIVAL_DAYS = 14
ARRIVAL_MIN = 5
ARRIVAL_SHARE = 0.6
ARRIVAL_RUN = 3  # this many days in a row at a new time is a change, before the 14 days turn


def day_of(ts: datetime) -> date:
    return ts.date() if ts.time() >= DAY_ENDS else ts.date() - timedelta(days=1)


def band(hour: int, bands=BANDS) -> str:
    return next((word for lo, hi, word in bands if lo <= hour < hi), "深夜")


def fragments(text: str) -> set[str]:
    """2-6 character pieces of his line, never across a generic word or a little word."""
    out = set()
    for run in CJK.findall(GENERIC.sub(" ", text)):
        for chunk in BREAK.split(run):
            for n in range(MIN_LEN, MAX_LEN + 1):
                out.update(chunk[i:i + n] for i in range(len(chunk) - n + 1))
    return out


def _his(conn: sqlite3.Connection, since: datetime, until: datetime) -> list[tuple[datetime, str]]:
    rows = conn.execute("SELECT ts, text FROM messages WHERE role = 'user' AND ts >= ? AND ts < ? ORDER BY ts",
                        (since.isoformat(timespec="seconds"), until.isoformat(timespec="seconds")))
    return [(datetime.fromisoformat(ts), text) for ts, text in rows]


def count(lines: list[tuple[datetime, str]], previous: list[dict] = ()) -> list[dict]:
    """The weekday patterns in his lines (the last WINDOW_DAYS days of them), merged with what
    the nights before found. Each: {"weekday": 0-6, "phrase", "weeks", "first", "last" (ISO
    days), "sample", "when" (a time of day), "status": active | lapsed, "misses", "checked"}."""
    said_on: dict[date, list[str]] = defaultdict(list)  # every line, questions too: he came that day
    days: dict[str, set[date]] = defaultdict(set)
    hours: dict[tuple[str, date], int] = {}
    samples: dict[str, str] = {}  # the latest line that says it
    for ts, text in lines:
        d = day_of(ts)
        said_on[d].append(text)
        if QUESTION.search(text) or OTHER_DAY.search(text):
            continue
        for g in fragments(text):
            days[g].add(d)
            hours.setdefault((g, d), ts.hour)
            if not secret(text):
                samples[g] = text[:30]
    talked = set(said_on)

    found = []
    for g, ds in days.items():
        weekday, n = Counter(d.weekday() for d in ds).most_common(1)[0]
        on = sorted(d for d in ds if d.weekday() == weekday)
        weeks = {d.isocalendar()[:2] for d in on}
        if len(weeks) < MIN_WEEKS or n / len(ds) < SHARE:
            continue
        span = sorted(d for d in talked if d.weekday() == weekday and on[0] <= d <= on[-1])
        if len(on) / len(span) < COVER or _streak(span, set(on)) < STREAK:
            continue
        when, same_time = Counter(band(hours[(g, d)]) for d in on).most_common(1)[0]
        if same_time / len(on) < SHARE:
            continue
        found.append({"weekday": weekday, "phrase": g, "on": on, "weeks": len(weeks),
                      "share": n / len(ds), "when": when})
    # one pattern for one habit: of the phrases said in the same lines, the one most bound to
    # its weekday, then said on more days, then the longest ("糖醋排骨", not "食堂" or "糖醋")
    found.sort(key=lambda p: (-p["share"], -len(p["on"]), -len(p["phrase"])))
    kept: list[dict] = []
    for p in found:
        if not any(k["weekday"] == p["weekday"] and _together(p, k, said_on) for k in kept):
            kept.append(p)
    # nor is it a new habit when it comes with one an earlier night found ("食堂" after the
    # 糖醋排骨 days have left the window)
    kept = [p for p in kept if not any(o["weekday"] == p["weekday"] and not _same(o, p)
                                       and _with(p, o["phrase"], said_on) for o in previous)]

    out = [{"weekday": p["weekday"], "phrase": p["phrase"], "weeks": p["weeks"],
            "first": p["on"][0].isoformat(), "last": p["on"][-1].isoformat(),
            "sample": samples.get(p["phrase"], ""), "when": p["when"]} for p in kept]
    for p in out:
        for old in previous:  # the same habit an earlier night saw: its longer history stays
            if _same(old, p):
                p["weeks"], p["first"] = max(p["weeks"], old["weeks"]), min(p["first"], old["first"])
        _lapse(p, said_on, refound=True)
    # what earlier nights found and these lines no longer show (said too long ago) is kept
    for old in previous:
        if not any(_same(old, p) for p in out):
            old = dict(old)
            _lapse(old, said_on, refound=False)
            out.append(old)
    out.sort(key=lambda p: (p["status"] != "active", -p["weeks"], p["last"]))
    return out[:KEPT]


def _streak(span: list[date], on: set[date]) -> int:
    best = run = 0
    for d in span:
        run = run + 1 if d in on else 0
        best = max(best, run)
    return best


def _together(p: dict, k: dict, said_on: dict[date, list[str]]) -> bool:
    """Part of the same habit: one is in the other, or they come in one line on half the days."""
    if p["phrase"] in k["phrase"] or k["phrase"] in p["phrase"]:
        return True
    return _with(min(p, k, key=lambda x: len(x["on"])), max(p, k, key=lambda x: len(x["on"]))["phrase"],
                 said_on)


def _with(p: dict, phrase: str, said_on: dict[date, list[str]]) -> bool:
    """On at least half of p's days, p's phrase came in one line with this phrase."""
    both = sum(any(p["phrase"] in t and phrase in t for t in said_on[d]) for d in p["on"])
    return both * 2 >= len(p["on"])


def _same(a: dict, b: dict) -> bool:
    return a["weekday"] == b["weekday"] and (a["phrase"] in b["phrase"] or b["phrase"] in a["phrase"])


def _lapse(p: dict, said_on: dict[date, list[str]], *, refound: bool) -> None:
    """Lapsed: the last LAPSE_AFTER times he talked on its weekday, he never said it. A day
    without him is no evidence either way, so months away leave a pattern as it was. A pattern
    the lines still show is checked from its last time; an older one goes on from the last day
    an earlier night checked, so no day is counted twice."""
    last = date.fromisoformat(p["last"])
    start, misses = last, 0
    if not refound:
        start = max(last, date.fromisoformat(p.get("checked", p["last"])))
        misses = p.get("misses", 0)
    for d in sorted(d for d in said_on if d.weekday() == p["weekday"] and d > start):
        if any(p["phrase"] in t for t in said_on[d]):
            p["last"], misses = d.isoformat(), 0
        else:
            misses += 1
    if said_on:
        p["checked"] = max(max(said_on), start).isoformat()
    p["misses"] = misses
    p["status"] = "lapsed" if misses >= LAPSE_AFTER else "active"


def count_patterns(conn: sqlite3.Connection, now: datetime, previous: list[dict] = ()) -> list[dict]:
    """The night's count, over his lines of the last WINDOW_DAYS days."""
    return count(_his(conn, now - timedelta(days=WINDOW_DAYS), now), previous)


# --- showing them -------------------------------------------------------------------------

def _details(p: dict, today: date) -> str:
    bits = [f"{p['weeks']} 个周{WEEKDAYS_CN[p['weekday']]}"]
    if p.get("when"):
        bits.append(f"多在{p['when']}")
    last = date.fromisoformat(p["last"])
    if (today - last).days > 14:
        bits.append(f"最近一次是{spoken(last, today)}")
    return "，".join(bits)


def pattern_lines(patterns: list[dict], today: date, *, asked: bool = False) -> list[str]:
    """On a pattern's weekday, that pattern; when he asks about a habit (一般/平时/每周), all of
    them, lapsed ones said to be so, at most SHOWN."""
    lines = []
    for p in patterns:
        day = f"周{WEEKDAYS_CN[p['weekday']]}"
        sample = f"，比如「{p['sample']}」" if p.get("sample") else ""
        if asked:
            lapsed = f"；后来 {p['misses']} 个{day}都没提了" if p.get("status") == "lapsed" else ""
            lines.append(f"程序数的：{day}他常说到「{p['phrase']}」（{_details(p, today)}）{sample}{lapsed}。")
        elif p.get("status") == "active" and p["weekday"] == today.weekday():
            lines.append(f"今天{day}：前几个{day}他都说到「{p['phrase']}」（{_details(p, today)}）{sample}。")
    return lines[:SHOWN]


def asks_habit(line: str) -> bool:
    return bool(USUALLY.search(line))


def arrival(firsts: list[datetime]) -> str:
    """When he usually comes, from the time of his first message on each of his days (oldest
    first, today left out). Empty until he has come on ARRIVAL_MIN days."""
    if len(firsts) < ARRIVAL_MIN:
        return ""
    recent, before = firsts[-ARRIVAL_DAYS:], firsts[-2 * ARRIVAL_DAYS:-ARRIVAL_DAYS]
    usual = _usual(recent)
    # a new time several days running, against an earlier habit, is a change before it is
    # most of the 14 days
    run = _run(firsts)
    if len(run) >= ARRIVAL_RUN:
        now_word = band(run[0].hour, ARRIVAL_BANDS)
        earlier = _usual(firsts[:-len(run)][-ARRIVAL_DAYS:])
        if (earlier and earlier[0] != now_word and len(earlier[1]) >= ARRIVAL_MIN
                and (usual is None or usual[0] != now_word)):
            return f"他最近 {len(run)} 次都是{_said(now_word, run)}来找你；之前多是{_said(*earlier)}来。"
    if usual is None:
        return f"他最近来找你的钟点不固定（最近 {len(recent)} 个聊天的日子）。"
    word, times = usual
    line = f"他最近多是{_said(word, times)}来找你（最近 {len(recent)} 个聊天的日子里有 {len(times)} 天）"
    earlier = _usual(before) if len(before) >= ARRIVAL_MIN else None
    if earlier and earlier[0] != word:
        line += f"；再早些时候多是{_said(*earlier)}来"
    return line + "。"


def _run(firsts: list[datetime]) -> list[datetime]:
    """The days at the end that all fall in one part of the day."""
    run: list[datetime] = []
    for t in reversed(firsts):
        if run and band(t.hour, ARRIVAL_BANDS) != band(run[0].hour, ARRIVAL_BANDS):
            break
        run.insert(0, t)
    return run


def _usual(firsts: list[datetime]) -> tuple[str, list[datetime]] | None:
    if not firsts:
        return None
    word, n = Counter(band(t.hour, ARRIVAL_BANDS) for t in firsts).most_common(1)[0]
    if n / len(firsts) < ARRIVAL_SHARE:
        return None
    return word, [t for t in firsts if band(t.hour, ARRIVAL_BANDS) == word]


def _said(word: str, times: list[datetime]) -> str:
    if word == "深夜":
        hours = sorted((t.hour + 24 if t.hour < 5 else t.hour) for t in times)
        return "深夜（23 点以后）" if hours[-1] < 24 else f"深夜（{hours[0] % 24}–{hours[-1] - 24} 点）"
    hours = sorted(t.hour for t in times)
    return f"{word}（{hours[0]} 点）" if hours[0] == hours[-1] else f"{word}（{hours[0]}–{hours[-1]} 点）"


def arrival_line(conn: sqlite3.Connection, now: datetime) -> str:
    """The line for this turn: his first message of each earlier day in the last WINDOW_DAYS."""
    start = datetime.combine(day_of(now), DAY_ENDS)
    firsts: dict[date, datetime] = {}
    for ts, _ in _his(conn, start - timedelta(days=WINDOW_DAYS), start):
        firsts.setdefault(day_of(ts), ts)
    return arrival(sorted(firsts.values()))

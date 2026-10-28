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
HABIT = re.compile(r"一般|每[周天个次回月年]|经常|总是|老是|平时")  # "what do I usually eat on Fridays" names no one day
# A day of the month, to 三十一: "十九号", "19号"
DAYNUM = r"(?:\d{1,2}|[二三]?十[一二三四五六七八九]?|[一二三四五六七八九])"
NOT_A_DAY = r"(?![线楼床房门室号院路车口码台位机店球])"  # 3号线, 5号楼, 8号床: not days
# What part of a month: "初" the first ten days, "中旬" the middle ten, "底" the rest
PARTS = r"上旬|中旬|下旬|初|中|底|末"
# Public holidays that fall on the same days every year (month, first day, last day). The ones of
# the lunar calendar move; without a calendar they name no days.
FESTIVALS = {"国庆": (10, 1, 7), "十一": (10, 1, 7), "元旦": (1, 1, 3), "五一": (5, 1, 5), "劳动节": (5, 1, 5)}
FESTIVAL = re.compile(r"国庆|元旦|劳动节|(?<![\d第月十])五一(?![\d月号点日个岁])|(?<![\d第月])十一(?![\d月号点日个岁])")
MONTH_OFF = {"上上": -2, "上": -1, "这": 0, "本": 0, "下": 1, "下下": 2}


def _n(s: str) -> int:
    return int(s) if s.isdigit() else NUM[s]


def day_num(s: str) -> int:
    """"19", "十九", "二十三", "七" as a number."""
    if s.isdigit():
        return int(s)
    if "十" in s:
        tens, _, ones = s.partition("十")
        return (NUM[tens] if tens else 1) * 10 + (NUM[ones] if ones else 0)
    return NUM[s]


def months_from(today: date, k: int) -> tuple[int, int]:
    """The year and month k months from today's."""
    y, m = divmod(today.month - 1 + k, 12)
    return today.year + y, m + 1


def _month(year: int, month: int, part: str = "") -> tuple[date, date]:
    last = monthrange(year, month)[1]
    lo, hi = {"初": (1, 10), "上旬": (1, 10), "中": (11, 20), "中旬": (11, 20), "底": (21, last),
              "末": (21, last), "下旬": (21, last)}.get(part, (1, last))
    return date(year, month, lo), date(year, month, hi)


# The time words `window` reads, to take them out of a cue when what is asked about is wanted:
# "我上周考的啥来着" asks about an exam, and "上周" is in every chat that retells an older one.
TIME_WORDS = re.compile(
    rf"{LAST_WEEK}[一二三四五六日天]?|{THIS_WEEK}|大前天|前天|前晚|昨[天晚儿日早]|{N}天前"
    rf"|前几天|前两天|这几天|最近几天|{N}\s*月\s*{N}\s*[号日]|{N}\s*月份?(?:{PARTS})?"
    rf"|(?:上上个?|上个?|这个?|本)月份?(?:{PARTS})?|去年"
    rf"|今[天晚早儿]|{WEEK}[一二三四五六日天]"
)


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
    if m := re.search(rf"{N}\s*月\s*{N}\s*[号日]", cue):
        month, day = _n(m.group(1)), _n(m.group(2))
        year = today.year - (1 if "去年" in cue or (month, day) > (today.month, today.day) else 0)
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        return d, d
    if m := FESTIVAL.search(cue):
        month, lo, hi = FESTIVALS[m.group(0)]
        year = today.year - (1 if "去年" in cue or (month, lo) > (today.month, today.day) else 0)
        return date(year, month, lo), date(year, month, hi)
    if m := re.search(rf"{N}\s*月(?:份)?({PARTS})?", cue):
        month = _n(m.group(1))
        if 1 <= month <= 12:
            year = today.year - (1 if "去年" in cue or month > today.month else 0)
            return _month(year, month, m.group(2) or "")
    # "上个月中旬", "上上个月底", "这个月初": a part of a month counted back from this one, never
    # past today
    if m := re.search(rf"(上上|上|这|本)个?月(?:份)?({PARTS})?", cue):
        year, month = months_from(today, MONTH_OFF[m.group(1)])
        lo, hi = _month(year, month, m.group(2) or "")
        return lo, min(hi, today) if lo <= today else hi
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
CN_DATE = re.compile(r"(?:(\d{4})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*([日号])")
WEEKDAY_WORD = re.compile(r"(?:周|星期|礼拜)([一二三四五六日天])")
# A birthday or an anniversary written without a year is a day of every year, not the day
# the note is about ("他的生日是3月14日" is said on 1/5 and about 1/5).
ANNUAL = re.compile(r"生日|纪念日|周年")
_RELATIVE = re.compile(
    r"大前天|(?<![以之从提])前[天晚]|昨[天晚儿日早]|今[天晚早儿]|明[天晚早儿]|大后天|(?<![以之然最])后天"
    rf"|(上上|下下|上|下|这|本){WEEK}([一二三四五六日天])"
    rf"|(?<![第\d一二三四五六七八九十]){N}天(?:前|后|以后|之后)"  # "第二天后" is the day after something
    rf"|(上上|下下|上|下|这|本)个?月({DAYNUM})\s*[号日]{NOT_A_DAY}"
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


def _relative_days(text: str, today: date, *, yearly_skip: bool = True) -> set[date]:
    """yearly_skip: "下个月十九号" next to 生日 names no day of the note (it is every year's);
    reading his line for the one day it names, it does."""
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
        elif m.group(4):  # "下个月十九号"; a birthday's is every year's (written_day)
            if yearly_skip and ANNUAL.search(text):
                continue
            year, month = months_from(today, MONTH_OFF[m.group(4)])
            if 1 <= (day := day_num(m.group(5))) <= monthrange(year, month)[1]:
                days.add(date(year, month, day))
        else:
            n = _n(m.group(3))
            days.add(today + timedelta(days=-n if word.endswith("前") else n))
    return days


def written_day(text: str, today: date) -> date | None:
    """The first date written out in a text ("2027-01-06", "1月13号"), not its time words.
    A birthday's day without a year is every year's, so it is not the one."""
    annual = bool(ANNUAL.search(text))
    for _, _, d, form in dates_in(text, today):
        if not (annual and form.startswith("cn") and not form.endswith("y")):
            return d
    return None


def _bigrams(text: str) -> set[str]:
    return {a + b for a, b in zip(text, text[1:]) if a.isalnum() and b.isalnum()}


def _about_the_note(said: str, text: str) -> bool:
    """His line dates the note only if the note shares a word with a clause of it that names a
    day: "明天开学了，对了我是学机械的" does not make "他是学机械的" tomorrow's."""
    note = _bigrams(text)
    for clause in re.split(r"[，。,；;！!？?、…~～\s]+", said):
        rest = CN_DATE.sub("|", ISO_DATE.sub("|", _RELATIVE.sub("|", clause)))
        if rest != clause and _bigrams(rest) & note:
            return True
    return False


def day_of(text: str, now: datetime, said: str = "") -> date | None:
    """The day a note is about: a date written in it; else the one day its time words name
    ("他明天面试", read at `now`); else the same from his line (`said`, the message the note
    came from), if the note shares a word with the part of it that names the day. None when
    nothing names exactly one day: the caller uses the message's day.
    A bare "周五" names no day (last Friday or the coming one) and neither do "上周", "最近"."""
    today = now.date()
    for words in (text, said if said and _about_the_note(said, text) else ""):
        if not words:
            continue
        if (d := written_day(words, today)) is not None:
            return d
        days = _relative_days(words, today)
        if len(days) == 1:
            return days.pop()
        if days:
            return None  # "明天面试，今天先复习": more than one day, so not this one
    return None


# --- writing: a date the model counted from his words (memory v3 §14.3) ---------------------------
# He said "大后天就我生日了" on 5/4; the model wrote "他的生日是2028-05-08". A date it wrote out is
# never read again by `absolute`, so the code counts his words itself and the near miss is moved.
NEAR_DAYS = 3  # a date this close to the day his line names is the model counting wrong
# Words that name a day the code cannot place, or a stretch of days: with one of them in his line,
# "the day his line names" is not known ("周五" last or next, "下周", "过几天", "19号" of which month).
_VAGUE_DAY = re.compile(
    rf"{WEEK}[一二三四五六日天末]|周末|(?:上上|下下|上|下|这|本)个?(?:{WEEK}|月)|月[初中底末]"
    r"|\d{1,2}\s*[号日]|[二三]?十[一二三四五六七八九]?[号日]|过[几两]天|这几天|改天|回头")


def line_day(said: str, today: date) -> date | None:
    """The one day his line names, counted here: "大后天" said on 2028-05-04 is 05-07,
    "下下周二", "下个月8号", "5月7号" too. `today` is the day he said it (her day: a line at 01:00
    belongs to the day before). None when it names no day, more than one ("明天面试，今天先复习"),
    a habit, or a day the code cannot place ("周五", "下周", "19号")."""
    if not said or HABIT.search(said):
        return None
    if _VAGUE_DAY.search(_RELATIVE.sub("|", CN_DATE.sub("|", ISO_DATE.sub("|", said)))):
        return None
    days = {d for _, _, d, _ in dates_in(said, today)} | _relative_days(said, today, yearly_skip=False)
    return days.pop() if len(days) == 1 else None


def agree_with_line(text: str, said: str, today: date, told: date | None = None) -> str:
    """A note's written-out dates ("2028-05-08") that miss the one day his line names by a few
    days become that day, with a weekday written right next to it. Untouched: a note his line does
    not date (no shared word with the part that names the day), one that already has the right
    day, a date far off (another thing), the day he said it (`told`, default `today`)."""
    day = line_day(said, today)
    if day is None or not _about_the_note(said, text):
        return text
    isos = [(a, b, d) for a, b, d, form in dates_in(text, today) if form == "iso"]
    if any(d == day for _, _, d in isos):
        return text
    said_on = {today, told or today}  # "他2028-05-04说……": the day he said it, by either clock
    out = text
    for a, b, d in reversed(isos):
        if d in said_on or not 0 < abs((d - day).days) <= NEAR_DAYS:
            continue
        tail = out[b:]
        if w := re.match(rf"\s*[（(]?\s*{WEEK}([一二三四五六日天])", tail):
            tail = tail[:w.start(1)] + WEEKDAYS_CN[day.weekday()] + tail[w.end(1):]
        head = out[:a]
        if w := re.search(rf"{WEEK}([一二三四五六日天])\s*[（(]?\s*$", head):
            head = head[:w.start(1)] + WEEKDAYS_CN[day.weekday()] + head[w.end(1):]
        out = head + day.isoformat() + tail
    return out


# --- writing: a note's time words as the days they name (memory v3 §14) -------------------------
# A note is read weeks after it was said: "他的生日是下个月19号" said on 3/17 read on 4/27 is May.
_DAY_OFF = {"大前天": -3, "前天": -2, "昨天": -1, "昨儿": -1, "昨日": -1, "今天": 0, "今儿": 0, "今日": 0,
            "明天": 1, "明儿": 1, "明日": 1, "后天": 2, "大后天": 3}
_PART_OF_DAY = {"昨晚": (-1, "晚上"), "昨早": (-1, "早上"), "今晚": (0, "晚上"), "今早": (0, "早上"),
                "明晚": (1, "晚上"), "明早": (1, "早上"), "前晚": (-2, "晚上")}
_YEAR_OFF = {"前年": -2, "去年": -1, "今年": 0, "明年": 1, "后年": 2}
# Words that only look like time words: 月饼, 月亮, 登上月球; 周围, 周边, 周期 (not 这周期末); 明日方舟,
# 今日头条 (names); "第二天后" (the day after, not two days from now).
NOT_A_MONTH = r"(?![饼亮球光色票嫂子])"
NOT_A_WEEK = r"(?![围边]|期(?![末中]))"
NOT_A_DAY_NAME = r"(?!方舟|头条|之后|香)"
_ABSOLUTE = re.compile(
    rf"(?P<mo>上上|下下|上|下|这|本)个?月{NOT_A_MONTH}(?:(?P<md>{DAYNUM})\s*(?P<mk>[号日]){NOT_A_DAY}|(?P<mp>{PARTS}))?"
    rf"|(?P<wk>上上|下下|上|下|这|本){WEEK}(?:(?P<wd>[一二三四五六日天])|{NOT_A_WEEK})"
    r"|(?P<pd>昨晚|昨早|今晚|今早|明晚|明早|(?<![以之从提])前晚)"
    rf"|(?P<d>大前天|大后天|(?<![以之从提])前天|(?<![以之然最])后天|[昨今明](?:[天儿]|日{NOT_A_DAY_NAME}))"
    rf"|(?<![第\d一二三四五六七八九十])(?P<nd>{DAYNUM})天(?P<nds>前|后|以后|之后)"
    r"|(?P<y>前年|去年|今年|明年|后年)"
)
# "9月15日(2027-09-15)" once the words are dates: the model had already written the day
_TWICE = re.compile(r"(\d{1,2})月(\d{1,2})([日号])?\s*[（(]\s*(\d{4})-0?\1-0?\2\s*[)）]")


def absolute(text: str, now: datetime) -> str:
    """The time words of a note as the days they name, read at `now` (when it was said):
    "下个月十九号" -> "4月19号", "下下周二" -> "9月28日周二", "昨晚" -> "1月10日晚上",
    "上周" -> "1月4日那周", "去年" -> "2026年". A habit ("每个月底") is not a day and stays; so do
    "3号线", "5号楼" and a day of the month said alone ("19号"), which may be a number of anything.
    A birthday or an anniversary keeps no year: it is every year's."""
    if HABIT.search(text):
        return text
    today = now.date()
    monday = today - timedelta(days=today.weekday())
    annual = bool(ANNUAL.search(text))

    def md(d: date) -> str:
        return f"{d.month}月{d.day}日"

    def sub(m: re.Match) -> str:
        g = m.groupdict()
        if g["mo"]:
            year, month = months_from(today, MONTH_OFF[g["mo"]])
            y = "" if year == today.year or annual else f"{year}年"
            if g["md"]:
                day = day_num(g["md"])
                return f"{y}{month}月{day}{g['mk']}" if 1 <= day <= monthrange(year, month)[1] else m.group(0)
            return f"{y}{month}月{g['mp'] or ''}"
        if g["wk"]:
            start = monday + timedelta(days=7 * MONTH_OFF[g["wk"]])
            if g["wd"]:
                d = start + timedelta(days=WEEKDAY[g["wd"]])
                return f"{md(d)}周{WEEKDAYS_CN[d.weekday()]}"
            return f"{md(start)}那周"
        if g["pd"]:
            k, part = _PART_OF_DAY[g["pd"]]
            return md(today + timedelta(days=k)) + part
        if g["d"]:
            return md(today + timedelta(days=_DAY_OFF[g["d"]]))
        if g["nd"]:
            n = day_num(g["nd"])
            return md(today + timedelta(days=-n if g["nds"] == "前" else n))
        return f"{today.year + _YEAR_OFF[g['y']]}年"

    out = _ABSOLUTE.sub(sub, text)
    return _TWICE.sub(lambda m: f"{m[1]}月{m[2]}{m[3] or '日'}" if annual
                      else f"{m[4]}-{int(m[1]):02d}-{int(m[2]):02d}", out)


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
        return f"{md}，{_cn(max(1, round(days / 7)))}周前"  # 27 days is about four weeks, not three
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


def told_day(memory: Memory) -> date | None:
    """The day to show next to a recalled memory, only when something names it. A row from
    before memory v3 has no `happened_on`: only a date written in it counts (its time words
    were read when a chat closed at night, a day late). A newer row whose day is just the day
    it was written, and whose words name no day ("他上周有个演示"), shows none."""
    created = datetime.fromisoformat(memory.created) if memory.created else None
    if not memory.happened_on:
        return written_day(memory.text, created.date()) if created else None
    d = date.fromisoformat(memory.happened_on)
    if created is None or d != created.date() or day_of(memory.text, created) is not None:
        return d
    return None


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
        hit = self.named_hit(cue, memory)
        return rel + hit * (1 - rel)

    def named_hit(self, cue: str, memory: Memory) -> float:
        """How much naming its days says about the memory (0 when it is not from them). A day
        or a week is a real reason to think of it, however few words they share (recall
        strengthens it, memory v3 §B4); a month or a year is a glance."""
        if not self.on_named_day(cue, memory):
            return 0.0
        lo, hi = self._window
        return time_hit((hi - lo).days + 1)

    def on_named_day(self, cue: str, memory: Memory) -> bool:
        """The memory is from the days the cue names."""
        if cue != self._cue:
            self._cue, self._window = cue, window(cue, self.now)
        if self._window is None:
            return False
        lo, hi = self._window
        return any(lo <= d <= hi for d in days_of(memory))

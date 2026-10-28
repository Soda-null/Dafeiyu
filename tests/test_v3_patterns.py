"""Memory v3 step 6, habits counted by code (docs/memory_v3_zh.md §3.3): what he says on one
weekday, counted at night from his own lines, and when he usually comes. Replayed over the two
scripted friends' lines (小周 starts Monday 2027-01-04, 小林 Monday 2027-09-06) and over
made-up noise; no model anywhere."""

from __future__ import annotations

import importlib.util
import json
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from fish.brain import Brain, FakeLLM
from fish.config import Settings
from fish.memory import Relationship, Window, arrival_line, asks_habit, count_patterns
from fish.memory.patterns import WINDOW_DAYS, arrival, count, day_of, pattern_lines
from fish.routines import run_nightly
from fish.storage import connect

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("checkup", ROOT / "scripts" / "checkup.py")
checkup = importlib.util.module_from_spec(spec)
sys.modules["checkup"] = checkup
spec.loader.exec_module(checkup)  # type: ignore[union-attr]
XIAOZHOU = json.loads((ROOT / "evals" / "xiaozhou_90d.json").read_text(encoding="utf-8"))
XIAOLIN = json.loads((ROOT / "evals" / "xiaolin_60d.json").read_text(encoding="utf-8"))
PERSONA = "你是大肥鱼。"


def his_lines(script: dict) -> list[tuple[datetime, str]]:
    start = date.fromisoformat(script["start"])
    return [(checkup.at(start, day, t), text)
            for day in range(1, script["days"] + 1) for t, text, _ in checkup.lines_for(script, day)]


def nights(lines: list[tuple[datetime, str]], start: date, days: int):
    """Each night's count, as the nightly routine does it: (day the night opens, patterns)."""
    patterns: list[dict] = []
    for day in range(2, days + 2):
        now = checkup.at(start, day, "03:30")
        patterns = count([(ts, x) for ts, x in lines if now - timedelta(days=WINDOW_DAYS) <= ts < now], patterns)
        yield day, patterns


@pytest.mark.parametrize("script, habit, found_by", [
    (XIAOZHOU, (4, "糖醋排骨"), 27),  # Fridays 5, 12, 19, 26: "今天食堂有糖醋排骨，爽"
    (XIAOLIN, (2, "吉他课"), 25),  # Wednesdays 3, 10, 17, 24: he never says "每周三"
], ids=["xiaozhou", "xiaolin"])
def test_each_scripted_friend_gives_exactly_his_one_habit(script, habit, found_by):
    start = date.fromisoformat(script["start"])
    ever, first = set(), None
    for day, patterns in nights(his_lines(script), start, script["days"]):
        ever |= {(p["weekday"], p["phrase"]) for p in patterns}
        if patterns and first is None:
            first = day
    assert ever == {habit}
    assert first == found_by


def test_ribs_lapse_after_three_fridays_without_them_and_she_is_told_so():
    start = date(2027, 1, 4)
    by_day = dict(nights(his_lines(XIAOZHOU), start, XIAOZHOU["days"]))
    # day 47 (a Friday, "今天食堂人好多"): still active, so it is shown that day
    ribs = by_day[47][0]
    assert (ribs["status"], ribs["weeks"], ribs["when"]) == ("active", 6, "中午")
    assert pattern_lines(by_day[47], date(2027, 2, 19)) == [
        "今天周五：前几个周五他都说到「糖醋排骨」（6 个周五，多在中午），比如「今天食堂有糖醋排骨，爽」。"]
    # day 60 (a Thursday): not its day, but "我周五一般吃啥" asks; two Fridays without it so far
    assert pattern_lines(by_day[60], date(2027, 3, 4)) == []
    assert asks_habit("我周五一般吃啥，你发现没")
    assert pattern_lines(by_day[60], date(2027, 3, 4), asked=True) == [
        "程序数的：周五他常说到「糖醋排骨」（6 个周五，多在中午，最近一次是2月12日，两周前），"
        "比如「今天食堂有糖醋排骨，爽」。"]
    # Fridays 47, 54, 61 he came and never said it: from the night after day 61 it has lapsed,
    # not shown on Fridays any more, and said to be so when he asks (day 90)
    assert by_day[61][0]["status"] == "active" and by_day[62][0]["status"] == "lapsed"
    assert pattern_lines(by_day[68], date(2027, 3, 12)) == []
    assert pattern_lines(by_day[90], date(2027, 4, 3), asked=True)[0].endswith("；后来 6 个周五都没提了。")


def test_guitar_on_day_52_and_after_months_away():
    start = date(2027, 9, 6)
    patterns = list(nights(his_lines(XIAOLIN), start, XIAOLIN["days"]))[-1][1]
    wed = date(2027, 10, 27)  # day 52, a Wednesday: "我周三晚上一般干嘛，你发现没" at 12:30
    assert pattern_lines(patterns, wed, asked=asks_habit("我周三晚上一般干嘛，你发现没"))[0].startswith(
        "程序数的：周三他常说到「吉他课」（7 个周三，多在晚上）")
    # 120 quiet nights: a day without him is no evidence, so the habit stays as it was
    later = count([], patterns)
    assert later[0]["status"] == "active"
    assert "最近一次是2027年11月3日，四个月前" in pattern_lines(later, date(2028, 3, 3), asked=True)[0]


def test_made_up_noise_finds_no_habit():
    """Every everyday line either scripted friend has (the two habits taken out), said on random
    days at random hours, several a day, for 90 days."""
    pool = [t for s in (XIAOZHOU, XIAOLIN) for t in
            [t for conv in s["filler"] for _, t in conv] + [t for d in s["scripted"].values() for _, t in d]
            if "糖醋排骨" not in t and "吉他" not in t]
    start = date(2027, 1, 4)
    for seed in range(8):
        r = random.Random(seed)
        lines = sorted(
            (datetime.combine(start + timedelta(days=day), datetime.min.time()) + timedelta(hours=r.uniform(7, 24)),
             r.choice(pool))
            for day in range(90) if r.random() > 0.15 for _ in range(r.randint(2, 10)))
        assert all(not p for _, p in nights(lines, start, 90)), seed


def test_questions_and_other_days_are_not_counted():
    fridays = [datetime(2027, 1, 8, 12) + timedelta(weeks=w) for w in range(5)]
    assert count([(t, "周五了，明天去爬山") for t in fridays]) == []  # about another day
    assert count([(t, "你记得我爱吃啥吗") for t in fridays]) == []  # a question
    assert [p["phrase"] for p in count([(t, "今天去游泳，累") for t in fridays])] == ["去游泳"]


def test_a_lapsed_habit_comes_back_when_he_says_it_again():
    fridays = [datetime(2027, 1, 8, 12) + timedelta(weeks=w) for w in range(8)]
    lines = [(t, "今天去游泳，累") for t in fridays[:4]] + [(t, "今天好困") for t in fridays[4:7]]
    patterns = count(lines)
    assert (patterns[0]["status"], patterns[0]["misses"]) == ("lapsed", 3)
    patterns = count(lines + [(fridays[7], "今天又去游泳了")], patterns)
    assert (patterns[0]["status"], patterns[0]["last"]) == ("active", "2027-02-26")


def test_when_he_usually_comes_turns_three_days_after_he_changes():
    start = date(2027, 1, 4)
    firsts: dict[date, datetime] = {}
    for ts, _ in his_lines(XIAOZHOU):
        firsts.setdefault(day_of(ts), ts)

    def line(day: int) -> str:
        today = start + timedelta(days=day - 1)
        return arrival(sorted(t for d, t in firsts.items() if d < today))

    assert line(5) == ""  # four days are not a habit yet
    assert line(8) == "他最近多是深夜（23 点以后）来找你（最近 7 个聊天的日子里有 7 天）。"
    # from day 8 on he comes in the day ("以后不熬夜了，白天找你"); one day is not a change
    assert line(10).startswith("他最近多是深夜")
    assert line(11) == "他最近 3 次都是白天（8–12 点）来找你；之前多是深夜（23 点以后）来。"
    # day 30, "我一般都啥时候找你聊天"
    assert line(30) == ("他最近多是白天（9–15 点）来找你（最近 14 个聊天的日子里有 13 天）；"
                        "再早些时候多是深夜（23 点以后）来。")


def make_brain(tmp_path: Path, llm):
    conn = connect(tmp_path / "fish.db")
    settings = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db")
    return Brain(conn, settings, llm, persona_text=PERSONA), conn


def today_of(llm: FakeLLM) -> str:
    system = llm.calls[-1][0][0]["content"]
    return system.split("## 今天", 1)[1].split("\n## ", 1)[0]


def test_the_night_counts_and_the_chat_shows_it(tmp_path):
    llm = FakeLLM(lambda messages, json_mode: json.dumps({"say": "嗯"}, ensure_ascii=False))
    brain, conn = make_brain(tmp_path, llm)
    window = Window(conn, 20)
    for w in range(5):  # five Fridays at lunch, and her own replies, which do not count
        friday = datetime(2027, 1, 8, 12, 0) + timedelta(weeks=w)
        window.append("user", "今天食堂有糖醋排骨，爽", "terminal", None, friday)
        window.append("fish", "糖醋排骨！周五快乐", "terminal", None, friday + timedelta(minutes=1))
    report = run_nightly(conn, datetime(2027, 2, 6, 3, 30))
    assert report["weekday_patterns"] == 1
    assert [p["phrase"] for p in Relationship(conn).patterns()] == ["糖醋排骨"]

    brain.respond("中午好", now=datetime(2027, 2, 12, 12, 0))  # a Friday
    shown = today_of(llm)
    assert "今天周五：前几个周五他都说到「糖醋排骨」（5 个周五，多在中午）" in shown
    assert "他最近多是白天（12 点）来找你（最近 5 个聊天的日子里有 5 天）。" in shown
    brain.respond("嗯", now=datetime(2027, 2, 13, 12, 0))
    assert "糖醋排骨" not in today_of(llm)
    brain.respond("我平时周五吃啥", now=datetime(2027, 2, 13, 12, 5))
    assert "程序数的：周五他常说到「糖醋排骨」" in today_of(llm)


def test_arrival_reads_his_first_message_of_each_earlier_day(tmp_path):
    conn = connect(tmp_path / "fish.db")
    window = Window(conn, 20)
    for day in range(6):
        t = datetime(2027, 1, 4, 23, 30) + timedelta(days=day)
        window.append("fish", "在吗", "terminal", None, t - timedelta(hours=12))  # hers do not count
        window.append("user", "睡不着", "terminal", None, t)
        window.append("user", "还是睡不着", "terminal", None, t + timedelta(hours=2))  # 01:30 is the same day
    now = datetime(2027, 1, 10, 9, 0)
    assert arrival_line(conn, now) == "他最近多是深夜（23 点以后）来找你（最近 6 个聊天的日子里有 6 天）。"
    assert count_patterns(conn, now) == []


def test_the_look_back_is_told_these_are_counted():
    text = (ROOT / "src" / "fish" / "brain" / "prompts" / "reflect.md").read_text(encoding="utf-8")
    assert "程序会照聊天记录数，你别把这些写成规律" in text

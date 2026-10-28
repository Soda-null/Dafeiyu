"""Memory v3 step 3, the days worked out by code (docs/memory_v3_zh.md §3.1, §2.1): the "today"
section, the day a note is about (`happened_on`), a date moved to the weekday written next to
it, and recalled memories shown with the day they happened. Dates are fixed; the friends are
the scripted ones (小周 starts 2027-01-05, 小林 2027-09-06)."""

import json
from datetime import date, datetime, timedelta

from fish.brain import Brain, FakeLLM
from fish.brain.prompt import build_close_messages, render_recalled
from fish.config import Settings
from fish.memory import MemoryStore, recall, today_section
from fish.memory.today import calendar, pattern_lines, yearly
from fish.memory.when import day_of, days_of, fix_weekday, spoken
from fish.storage import connect

WED = datetime(2027, 1, 20, 20, 0)  # 小周 day 16, a Wednesday
PERSONA = "你是大肥鱼。"


def chat_json(say="嗯。", notes=()) -> str:
    return json.dumps({"say": say, "mood": "平静", "topic": "闲聊", "notes": list(notes),
                       "followups": [], "asked": [], "corrections": []}, ensure_ascii=False)


def make_brain(tmp_path, notes=()):
    conn = connect(tmp_path / "fish.db")
    settings = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db",
                        window_size=20)
    llm = FakeLLM(lambda messages, json_mode: chat_json(notes=notes))
    return Brain(conn, settings, llm, persona_text=PERSONA), conn, llm


def section(system: str, title: str) -> str:
    return system.split(f"## {title}", 1)[1].split("\n## ", 1)[0]


# --- the day a note is about ---------------------------------------------------------------

def test_a_date_is_moved_to_the_weekday_written_next_to_it(tmp_path):
    store = MemoryStore(connect(tmp_path / "fish.db"))
    # 小周 #45: he said "这周六", the model wrote the 24th; that Saturday is the 23rd.
    m = store.note("event", "他2027-01-24周六要去上海看演唱会，抢到票了", importance=5, now=WED)
    assert m.text == "他2027-01-23周六要去上海看演唱会，抢到票了" and m.happened_on == "2027-01-23"
    today = WED.date()
    assert fix_weekday("他1月24日（周六）去上海", today) == "他1月23日（周六）去上海"
    assert fix_weekday("他星期六 2027年1月24日去上海", today) == "他星期六 2027年1月23日去上海"
    assert fix_weekday("他2027-01-13周三有机械设计期中考", today) == "他2027-01-13周三有机械设计期中考"
    assert fix_weekday("他周五说2027-01-24去上海", today) == "他周五说2027-01-24去上海"  # not next to it
    # a weekday later in the note is checked against the date next to it, not the first one
    assert (fix_weekday("他2027-01-21周四说下周六2027-01-31去", today)
            == "他2027-01-21周四说下周六2027-01-30去")


def test_the_day_a_note_is_about():
    assert day_of("他2027-01-06晚上和室友吃了麻辣烫", WED) == date(2027, 1, 6)
    assert day_of("他1月13号有期中考", WED) == date(2027, 1, 13)
    assert day_of("他12月30号吃了火锅", datetime(2027, 1, 2)) == date(2026, 12, 30)  # nearest year
    assert day_of("他明天面试", WED) == date(2027, 1, 21)
    assert day_of("他昨晚吃了麻辣烫", WED) == date(2027, 1, 19)
    assert day_of("他上上周三考试", WED) == date(2027, 1, 6)
    # 小林 day 8 (Monday 9/13): "下下周二" is 9/28
    assert day_of("他下下周二去深圳总部述职", datetime(2027, 9, 13, 21, 0)) == date(2027, 9, 28)
    # the note names no day: his line does
    assert day_of("他在准备面试", WED, said="我明天面试，紧张") == date(2027, 1, 21)
    # nothing names exactly one day
    assert day_of("他在复习", WED, said="我明天面试，今天先复习") is None
    assert day_of("他周五吃排骨", WED) is None  # last Friday or the coming one
    assert day_of("他以前天天熬夜", WED) is None  # 以前天天 is not 前天
    assert day_of("他的生日是3月14日", WED) is None  # a day of every year, said today
    assert day_of("他2027-03-14生日这天吃了火锅", WED) == date(2027, 3, 14)


def test_notes_carry_the_day_they_happened(tmp_path):
    brain, conn, _ = make_brain(tmp_path, notes=[
        {"text": "他和室友吃了麻辣烫", "kind": "event", "about": "路过", "tags": ["吃的"]}])
    brain.respond("昨晚跟室友吃了麻辣烫", now=WED)
    store = MemoryStore(conn)
    (m,) = store.alive()
    assert m.happened_on == "2027-01-19" and m.created.startswith("2027-01-20")
    assert days_of(m) == {date(2027, 1, 19)}  # found by "前天晚上", not by the day she wrote it
    plain = store.note("fact", "他住7号楼", importance=5, now=WED)
    assert plain.happened_on == "2027-01-20"
    fixed = store.correct(m.id, "他和室友吃的是火锅", now=WED + timedelta(days=1))
    assert fixed.happened_on == "2027-01-19"  # a correction keeps the day
    merged = store.merge([plain.id, store.note("fact", "他住在7号楼那边", importance=5,
                                                now=WED + timedelta(days=3)).id],
                         "他住7号楼", now=WED + timedelta(days=4))
    assert merged.happened_on == "2027-01-23"  # the latest of its sources


def test_a_row_from_before_v3_is_dated_by_when_it_was_written(tmp_path):
    conn = connect(tmp_path / "fish.db")
    store = MemoryStore(conn)
    m = store.add("event", "他吃了麻辣烫", importance=3, now=datetime(2027, 1, 7, 3, 30))
    conn.execute("UPDATE memories SET happened_on = NULL WHERE id = ?", (m.id,))
    assert days_of(store.get(m.id)) == {date(2027, 1, 7)}
    assert store.planned_for([date(2027, 1, 7)]) == []


# --- saying a day ---------------------------------------------------------------------------

def test_days_are_said_the_way_he_would_say_them():
    today = WED.date()
    assert spoken(date(2027, 1, 19), today) == "昨天 1月19日"
    assert spoken(date(2027, 1, 23), today) == "这周六 1月23日"
    assert spoken(date(2027, 1, 13), today) == "上周三 1月13日"
    assert spoken(date(2027, 1, 6), today) == "上上周三 1月6日"
    assert spoken(date(2027, 2, 2), today) == "下下周二 2月2日"
    assert spoken(date(2026, 12, 20), today) == "2026年12月20日，一个月前"
    assert spoken(date(2027, 3, 1), today) == "3月1日，40天后"
    assert spoken(date(2027, 1, 6), date(2027, 3, 14)) == "1月6日，两个月前"


def test_recalled_lines_start_with_the_day_it_happened(tmp_path):
    store = MemoryStore(connect(tmp_path / "fish.db"))
    # 小周 day 10 (Thursday 1/14) asks "上周三晚上我吃的啥"
    store.note("event", "他2027-01-06晚上和室友吃了麻辣烫", importance=3, tags=["麻辣烫"],
               now=datetime(2027, 1, 6, 23, 20))
    got = recall(store, "麻辣烫", datetime(2027, 1, 14, 21, 0))
    assert "（上周三 1月6日）他2027-01-06晚上和室友吃了麻辣烫" in render_recalled(got, date(2027, 1, 14))
    assert render_recalled(got).startswith(f"- [#{got[0].memory.id}] 他2027")  # no day given, none shown


# --- the "today" section -----------------------------------------------------------------------

def test_the_date_table_names_every_day_she_may_need():
    table = calendar(WED.date())
    assert "昨天 1/19 周二，前天 1/18 周一" in table
    assert "这周（一到日）：一1/18 二1/19 三1/20 四1/21 五1/22 六1/23 日1/24" in table
    assert "下周：一1/25" in table and "日1/31" in table and "下下周二 2/2" in table


def test_her_card_says_when_his_birthday_is_today_or_soon(tmp_path):
    brain, conn, llm = make_brain(tmp_path)
    store = MemoryStore(conn)
    # 小周 #6, word for word
    store.note("fact", "他的生日是3月14日，让我到时候记得给他过。", importance=9, about="一辈子",
               now=datetime(2027, 1, 5, 21, 0))
    brain.respond("早啊", now=datetime(2027, 3, 14, 9, 0))  # 小周 day 70
    assert "今天是他生日（3月14日）！" in section(llm.calls[-1][0][0]["content"], "今天")
    card = store.profile()
    assert yearly(card, date(2027, 3, 12)) == ["再过 2 天是他生日（3月14日）。"]
    assert yearly(card, date(2027, 3, 10)) == []
    assert yearly(card, date(2027, 3, 15)) == []  # past for this year, a year away again
    sister = store.add("fact", "他妹妹小雨的生日是十二月三十一号", importance=8, now=WED)
    assert yearly([sister], date(2027, 12, 30)) == ["再过 1 天是他妹妹小雨生日（12月31日）。"]
    assert yearly([sister], date(2028, 12, 31), him="她") == ["今天是他妹妹小雨生日（12月31日）！"]


def test_what_he_planned_comes_up_on_the_day(tmp_path):
    # 小林 day 8 (Monday 9/13) says "下下周二" he goes to Shenzhen; day 23 (9/28) he only says "早，困死"
    brain, conn, llm = make_brain(tmp_path, notes=[
        {"text": "他下下周二去深圳总部述职", "kind": "event", "about": "日常", "tags": ["深圳", "述职"]}])
    brain.respond("我下下周二要去深圳总部述职，好烦", now=datetime(2027, 9, 13, 21, 0))
    store = MemoryStore(conn)
    (trip,) = store.alive()
    assert trip.happened_on == "2027-09-28"
    brain.llm = FakeLLM(lambda messages, json_mode: chat_json())

    brain.respond("我哪天去深圳来着", now=datetime(2027, 9, 20, 12, 30))  # 小林 day 15
    system = brain.llm.calls[-1][0][0]["content"]
    assert f"[#{trip.id}] （下周二 9月28日）他下下周二去深圳总部述职" in section(system, "这句话让你想起的")
    assert "述职" not in section(system, "今天")

    brain.respond("明天要早起", now=datetime(2027, 9, 27, 22, 0))
    assert ("明天：他下下周二去深圳总部述职（上上周一 9月13日说的）"
            in section(brain.llm.calls[-1][0][0]["content"], "今天"))
    brain.respond("早，困死", now=datetime(2027, 9, 28, 7, 40))  # 小林 day 23
    assert ("今天：他下下周二去深圳总部述职（上上周一 9月13日说的）"
            in section(brain.llm.calls[-1][0][0]["content"], "今天"))
    # news from today is not a plan: the chat it came from is in front of her
    store.note("event", "他今天去深圳了", importance=5, now=datetime(2027, 9, 28, 8, 0))
    assert [m.id for m in store.planned_for([date(2027, 9, 28)])] == [trip.id]


def test_a_weekday_pattern_shows_on_its_day_only():
    friday = [{"weekday": 4, "phrase": "糖醋排骨", "weeks": 6, "sample": "今天食堂有糖醋排骨，爽",
               "status": "active"}]
    assert pattern_lines(friday, date(2027, 1, 22)) == [
        "今天周五：前几个周五他都说到「糖醋排骨」（6 个周五），比如「今天食堂有糖醋排骨，爽」。"]
    assert pattern_lines(friday, date(2027, 1, 21)) == []
    assert pattern_lines([dict(friday[0], status="lapsed")], date(2027, 1, 22)) == []
    text = today_section(datetime(2027, 1, 22, 12, 0), [], [], patterns=friday, arrival="他最近都是中午来。")
    assert text.endswith("比如「今天食堂有糖醋排骨，爽」。\n他最近都是中午来。")


def test_the_close_sees_the_weekday_of_the_chat():
    content = build_close_messages("", [], [], "2027-01-20")[0]["content"]
    assert "今天是 2027-01-20 周三。" in content

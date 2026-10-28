"""Memory v3 §14.3: the day his line names is counted by code, and a date the model wrote a few
days off it is moved. He said "大后天就我生日了" on a Thursday evening; the model wrote
"他的生日是2028-05-08" and she said 5月8号 three times. The model is a fake; places are Springfield."""

import json
from datetime import date, datetime
from pathlib import Path

from fish.brain import Brain, FakeLLM
from fish.config import Settings
from fish.memory import MemoryStore
from fish.memory.today import calendar
from fish.memory.when import agree_with_line, line_day
from fish.storage import connect

THU = datetime(2028, 5, 4, 21, 0)  # 大后天 is Sunday 5/7


def chat_json(notes) -> str:
    return json.dumps({"say": "大后天？5月8号啊", "mood": "开心", "topic": "生日", "notes": notes,
                       "followups": [], "asked": [], "corrections": []}, ensure_ascii=False)


def make_brain(tmp_path: Path, notes) -> tuple[Brain, MemoryStore]:
    def answer(messages, json_mode):
        if "这次和他的聊天结束了" in messages[0]["content"]:
            return json.dumps({"summary": "聊了几句", "gist": "聊了几句", "notes": []}, ensure_ascii=False)
        return chat_json(notes)

    conn = connect(tmp_path / "fish.db")
    settings = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db")
    return Brain(conn, settings, FakeLLM(answer), persona_text="你是大肥鱼。"), MemoryStore(conn)


def test_his_birthday_counted_wrong_by_the_model_is_the_day_his_words_name(tmp_path):
    brain, store = make_brain(tmp_path, [
        {"text": "他的生日是2028-05-08", "kind": "fact", "about": "一辈子", "tags": ["生日"]},
        {"text": "他2028-05-08周一过生日，想吃蛋糕", "kind": "event", "about": "日常", "tags": ["生日"]}])
    brain.respond("大后天就我生日了", now=THU)
    fact, event = sorted(store.alive(), key=lambda m: m.kind != "fact")
    assert fact.text == "他的生日是2028-05-07" and fact.happened_on == "2028-05-07" and fact.pinned
    assert event.text == "他2028-05-07周日过生日，想吃蛋糕" and event.happened_on == "2028-05-07"


def test_the_day_his_line_names_across_month_and_year_ends():
    assert line_day("大后天就我生日了", date(2028, 5, 4)) == date(2028, 5, 7)
    assert line_day("后天交报告", date(2028, 2, 28)) == date(2028, 3, 1)  # 2028 has a Feb 29
    assert line_day("后天交报告", date(2027, 2, 28)) == date(2027, 3, 2)
    assert line_day("明天跨年去Springfield广场", date(2027, 12, 31)) == date(2028, 1, 1)
    assert line_day("大后天回家", date(2027, 12, 30)) == date(2028, 1, 2)
    assert line_day("下周二面试", date(2028, 1, 30)) == date(2028, 2, 1)
    assert line_day("下下周二述职", date(2027, 12, 22)) == date(2028, 1, 4)
    assert line_day("下个月8号我生日", date(2027, 12, 20)) == date(2028, 1, 8)
    assert line_day("1月2号回家", date(2027, 12, 30)) == date(2028, 1, 2)


def test_a_line_that_names_no_day_or_several_or_a_vague_one_names_none():
    today = date(2028, 5, 4)
    for said in ("我生日快到了", "明天面试，今天先复习", "周五考试", "下周考试", "过几天回家",
                 "19号考试", "每周三明天这种日子都要早起", "这个月底搬家"):
        assert line_day(said, today) is None, said


def test_only_a_near_miss_on_a_note_his_line_dates_is_moved():
    today = date(2027, 12, 30)
    said = "大后天回家"  # 2028-01-02
    assert agree_with_line("他2028-01-03回家", said, today) == "他2028-01-02回家"
    assert agree_with_line("他2028-01-02回家", said, today) == "他2028-01-02回家"  # right already
    assert agree_with_line("他2027-12-30说要回家，2028-01-03到", said, today) == "他2027-12-30说要回家，2028-01-02到"
    assert agree_with_line("他2028-01-09回家", said, today) == "他2028-01-09回家"  # a week off: another thing
    assert agree_with_line("他2027-01-02回家", said, today) == "他2027-01-02回家"  # a year off: not counting
    # a day already gone is not a miscount of the coming day his line names, nor the other way round
    assert (agree_with_line("他上次考试是2028-05-03，明天又考", "明天考试", date(2028, 5, 4))
            == "他上次考试是2028-05-03，明天又考")
    assert agree_with_line("他2028-05-05还要考试", "昨天考试了", date(2028, 5, 4)) == "他2028-05-05还要考试"
    assert agree_with_line("他2028-05-02考试", "昨天考试了", date(2028, 5, 4)) == "他2028-05-03考试"
    # two near dates: which one his day is is not known, so neither moves (a range does not collapse)
    assert (agree_with_line("他2028-05-06到2028-05-08出差", "明天出差", date(2028, 5, 4))
            == "他2028-05-06到2028-05-08出差")
    assert agree_with_line("他2028-05-06出差，2028-05-06出发", "明天出差", date(2028, 5, 4)).count("2028-05-05") == 2
    # his line does not date this note: no word shared with the part that names the day
    assert agree_with_line("他奶奶的生日是2028-01-01", "大后天回家", today) == "他奶奶的生日是2028-01-01"
    # several days or none: untouched
    assert agree_with_line("他2028-01-01面试", "明天面试，今天先复习", today) == "他2028-01-01面试"
    assert agree_with_line("他2028-01-01面试", "面试好紧张", today) == "他2028-01-01面试"


def test_a_line_after_midnight_counts_from_the_calendar_date(tmp_path):
    store = MemoryStore(connect(tmp_path / "fish.db"))
    late = datetime(2028, 5, 5, 1, 0)  # after midnight: 明天 is 5/6, as her date table says
    m = store.note("event", "他2028-05-07考高数", importance=5, about="日常", now=late,
                   said="明天考高数，睡不着", heard="chat")
    assert m.text == "他2028-05-06考高数" and m.happened_on == "2028-05-06"
    # a note that already agrees with the date table is left alone
    m = store.note("event", "他2028-05-06考高数", importance=5, about="日常", now=late,
                   said="明天考高数，复习不完", heard="chat")
    assert m.text == "他2028-05-06考高数"


def test_notes_not_heard_from_him_are_not_moved(tmp_path):
    store = MemoryStore(connect(tmp_path / "fish.db"))
    m = store.note("event", "他2028-05-08过生日", importance=5, about="日常", now=THU, said="大后天就我生日了")
    assert m.text == "他2028-05-08过生日"


def test_the_date_table_names_tomorrow_and_the_two_days_after():
    table = calendar(date(2028, 5, 4))
    assert "明天 5/5 周五，后天 5/6 周六，大后天 5/7 周日。" in table
    assert "明天 1/1 周六，后天 1/2 周日，大后天 1/3 周一。" in calendar(date(2021, 12, 31))

"""Recall by time (memory v2 step 5): time words in a cue become days, and a memory from
those days counts as relevant even when no word matches."""

from datetime import date, datetime

from fish.memory import BigramEmbedder, MemoryStore
from fish.memory.when import TimeCued, dates_in, days_of, window, written_day
from fish.storage import connect

WED = datetime(2027, 1, 20, 20, 10)  # a Wednesday evening


def test_time_words_become_days():
    assert window("昨晚我吃的啥", WED) == (date(2027, 1, 19), date(2027, 1, 19))
    assert window("我上周考的啥来着", WED) == (date(2027, 1, 11), date(2027, 1, 17))
    assert window("上周三晚上我吃的啥", WED) == (date(2027, 1, 13), date(2027, 1, 13))
    assert window("一月初有天晚上", WED) == (date(2027, 1, 1), date(2027, 1, 10))
    assert window("去年一月我考的啥", WED) == (date(2026, 1, 1), date(2026, 1, 31))
    assert window("1月6号干嘛了", WED) == (date(2027, 1, 6), date(2027, 1, 6))
    assert window("三天前", WED) == (date(2027, 1, 16), date(2027, 1, 18))
    # with the spaces many people type between digits and words
    assert window("我 1 月 6 号干嘛了", WED) == (date(2027, 1, 6), date(2027, 1, 6))
    assert window("你 1 月份记得我干嘛了吗", WED) == (date(2027, 1, 1), date(2027, 1, 31))


def test_a_spaced_date_in_a_note_is_still_its_day():
    today = WED.date()
    assert [d for _, _, d, _ in dates_in("他 1 月 13 号考试", today)] == [date(2027, 1, 13)]
    assert written_day("他 1 月 13 号考试", today) == date(2027, 1, 13)
    assert written_day("他生日是 3 月 14 日", today) is None  # a birthday is every year's


def test_habits_and_plain_questions_name_no_time():
    assert window("我周五一般吃啥", WED) is None
    assert window("我之前去上海干嘛了", WED) is None
    assert window("你记得我学啥的不", WED) is None


def test_a_memory_from_last_night_is_found_without_a_shared_word(tmp_path):
    store = MemoryStore(connect(tmp_path / "fish.db"))
    m = store.add("fact", "他2027-01-19晚上和室友吃了麻辣烫", importance=3, now=datetime(2027, 1, 19, 23, 0))
    assert days_of(m) == {date(2027, 1, 19)}
    words = BigramEmbedder()
    assert words.relevance("昨晚我吃的啥你记得不", m) == 0
    assert TimeCued(words, WED).relevance("昨晚我吃的啥你记得不", m) >= 0.6
    assert TimeCued(words, WED).relevance("我最爱吃啥", m) == words.relevance("我最爱吃啥", m)

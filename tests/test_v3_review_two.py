"""Memory v3, the review of the round-two fixes (docs/memory_v3_zh.md §14): the echo check dropped
facts he confirmed in a word or said in Chinese numerals; ordinary lines of his ("等我到家给你发消息",
"我爸答应我……", "我们班说好了……") and his habits became pinned promises; the "nothing came back"
reminder fired with the answer in the recalled block; "明日方舟", "月饼", "周围" were rewritten as
days. The model is a fake and everything in here is made up (Springfield)."""

from datetime import datetime, timedelta

import pytest

from fish.memory import (BigramEmbedder, MemoryStore, TimeCued, cue_for, echoes_her, his_line, may_answer,
                         promised_in_words, recall)
from fish.memory.retrieval import TOUCH_RELEVANCE
from fish.memory.when import absolute, day_of
from fish.memory.window import answered
from fish.storage import connect

from test_v3_round_two import T0, chat_json, make_brain


def chat(tmp_path, turns):
    """turns: (his line, her say, her notes); the memories alive after them."""
    reply = {}
    brain, conn, llm = make_brain(tmp_path, lambda m, j: chat_json(say=reply["say"], notes=reply["notes"]))
    for i, (his, say, notes) in enumerate(turns):
        reply.update(say=say, notes=notes)
        brain.respond(his, now=T0 + timedelta(minutes=i))
    return [m.text for m in MemoryStore(conn).alive()], llm


def event(text, kind="event"):
    return [{"text": text, "kind": kind, "about": "日常"}]


# --- what he confirms in a word is his ---------------------------------------------------------

@pytest.mark.parametrize("asked, answer, note", [
    ("面试怎么样了？", "过了！", "他面试过了"),
    ("期末考试咋样？", "砸了，别提了", "他期末考试考砸了"),
    ("你是不是下周三面试？", "对", "他2月3日周三面试"),  # written as the day it names
])
def test_a_follow_up_he_answers_in_a_word_is_written(tmp_path, asked, answer, note):
    notes = event(note.replace("2月3日周三", "下周三"))
    written, _ = chat(tmp_path, [("在吗", asked, []), (answer, "好", notes)])
    assert written == [note]


def test_her_question_he_answers_counts_as_his_even_when_he_asked_her_to_remember(tmp_path):
    written, _ = chat(tmp_path, [("我上次说的那件事你还记得吗", "面试怎么样了？", []),
                                 ("过了！", "太好了", event("他面试过了"))])
    assert written == ["他面试过了"]


def test_a_no_a_laugh_or_a_long_line_is_not_a_word_of_yes():
    assert answered("是暖气不热吧？", "对") == "是暖气不热吧？"
    assert answered("好呀。你是不是周三面试？", "嗯") == "你是不是周三面试？"
    for answer in ("不是", "哈哈", "你猜", "啥？", "过了，不过那个面试官问了一堆奇怪的问题"):
        assert answered("是暖气不热吧？", answer) == ""
    assert answered("好吧", "对") == ""  # no question of hers


def test_a_guess_is_still_not_his_when_he_asked_and_said_no(tmp_path):
    written, _ = chat(tmp_path, [("我新家有啥毛病来着", "是暖气不热、卫生间漏水吧？", []),
                                 ("不是", "那我忘了", event("他新家暖气不热，卫生间漏水", "fact"))])
    assert written == []


def test_a_number_he_said_in_words_is_the_number_she_wrote():
    his = "我新租的房子一个月两千八，一个人住"
    assert not echoes_her("他一个人住，月租2800", his, "2800？一个人住也太贵了")
    assert not echoes_her("他房租1500", "我房租一千五", "1500还行")
    assert echoes_her("他房租1500", "我房租多少来着", "一千五吧？")  # only she said it, in any writing


def test_a_rent_he_said_in_words_is_written(tmp_path):
    written, _ = chat(tmp_path, [("我新租的房子一个月两千八，一个人住", "2800？一个人住也太贵了",
                                  event("他一个人住，月租2800", "fact"))])
    assert written == ["他一个人住，月租2800"]


# --- what is a promise between them -------------------------------------------------------------

@pytest.mark.parametrize("line", [
    "等我到家给你发消息",
    "等我下班给你打电话",
    "我们班说好了周五聚餐",
    "我爸答应我考上就给我买车",
    "我答应我妈周末回家",
    "我跟我妈说好了我周末回家",
    "我们组约好了明天一起开会",
    "咱们宿舍说好一起去爬山",
    "老张答应我下周还钱",
    "我一般等忙完以后给你回",
])
def test_an_everyday_line_or_somebody_elses_promise_is_no_pact(line):
    assert his_line(line) is None


@pytest.mark.parametrize("line, who", [
    ("我答应你，等放假去 Springfield 给你带风筝", "him"),
    ("答应我，以后别熬夜了", "her"),
    ("那你可得答应我别生气", "her"),
    ("咱俩说好了，周末一起放风筝", "both"),
    ("我们说好了，等你回来一起去吃火锅", "both"),
    ("等我陶艺课结课那天，你给我写首诗，就这么说定了", "her"),
    ("等期末考完我去海边，给你拍海的照片", "him"),
])
def test_a_promise_between_them_is_still_one(line, who):
    assert his_line(line) == who


def test_an_everyday_line_writes_no_pact(tmp_path):
    brain, conn, _ = make_brain(tmp_path)
    for i, line in enumerate(["等我到家给你发消息", "我爸答应我考上就给我买车", "我们班说好了周五聚餐"]):
        brain.respond(line, now=T0 + timedelta(minutes=i))
    assert MemoryStore(conn).alive() == []


def test_without_a_note_only_a_promise_said_in_words_is_kept_from_his_line(tmp_path):
    assert promised_in_words("我答应你，放假给你带风筝") and not promised_in_words("等期末考完给你拍海的照片")
    brain, conn, _ = make_brain(tmp_path)
    brain.respond("等期末考完我去海边，给你拍海的照片", now=T0)
    assert MemoryStore(conn).pacts() == []  # a plan, until a note of hers says it is a promise
    brain.respond("我答应你，放假给你带风筝", now=T0 + timedelta(minutes=1))
    assert [(p.text, p.pact) for p in MemoryStore(conn).pacts()] == [("他说：「我答应你，放假给你带风筝」", "him")]


def test_a_habit_noted_as_an_insight_stays_an_insight(tmp_path):
    store = MemoryStore(connect(tmp_path / "fish.db"))
    m = store.note("insight", "他总是等忙完以后给我回消息", importance=5, now=T0, heard="chat")
    assert (m.kind, m.pact, m.pact_state) == ("insight", None, None)
    fact = store.note("fact", "他一般等下课了给我讲学校的事", importance=5, now=T0, heard="chat")
    assert fact.pact is None
    kept = store.note("insight", "他答应我，陶艺课结课后给我捏个小鱼", importance=6, now=T0, heard="chat")
    assert (kept.kind, kept.pact) == ("fact", "him")


# --- the "nothing came back" reminder -----------------------------------------------------------

def test_no_reminder_when_a_recalled_memory_holds_the_answer(tmp_path):
    brain, conn, llm = make_brain(tmp_path)
    store = MemoryStore(conn)
    store.note("event", "他和室友阿强一起去吃了火锅，辣到哭", importance=5, about="日常", now=T0)
    question = "我跟谁去吃的火锅来着"
    now = T0 + timedelta(days=2)
    back = recall(store, cue_for(question, ""), now, embedder=TimeCued(BigramEmbedder(), now))
    assert back and all(r.relevance < TOUCH_RELEVANCE for r in back)  # found for a word or two
    brain.respond(question, now=now)
    sent = llm.calls[-1][0]
    assert "阿强" in sent[0]["content"] and "什么也没想起来" not in sent[-1]["content"]


def test_a_word_in_common_is_what_he_asks_about_not_how():
    assert may_answer("我最近在学啥乐器来着", "他最近在学吉他，手指头都按疼了")
    assert not may_answer("我最近买的那个东西叫啥来着", "他最近在学吉他")  # only 最近 in common
    assert not may_answer("我那只猫叫啥来着，突然想不起来了", "他工作又紧起来了")  # not the asking clause


# --- words that only look like time words --------------------------------------------------------

@pytest.mark.parametrize("text", [
    "他在玩明日方舟", "他觉得今日头条很烂", "他买了这月饼", "他说这月亮真圆", "他想登上月球",
    "他家这周围很吵", "他公司这周边很多店", "他第二天后就好了", "他第十二天后拆了线",
])
def test_a_word_that_only_looks_like_a_time_word_is_kept(text):
    assert absolute(text, datetime(2027, 10, 3, 12)) == text


@pytest.mark.parametrize("text, written", [
    ("他明日出发", "他10月4日出发"),
    ("他这周期末考试", "他9月27日那周期末考试"),
    ("他十二天后回来", "他10月15日回来"),
    ("他这个月底搬家", "他10月底搬家"),
])
def test_the_time_words_next_to_them_still_are_days(text, written):
    assert absolute(text, datetime(2027, 10, 3, 12)) == written


def test_the_day_after_is_not_two_days_from_now():
    assert day_of("他第二天后就好了", datetime(2027, 10, 3, 12)) is None

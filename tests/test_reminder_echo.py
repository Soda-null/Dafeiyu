"""The reminder we put after his line must never come back out as her words (10-31: it went out
as a bubble when she answered in plain lines instead of JSON)."""

import json

from fish.brain.parse import clean_say, parse_reply
from fish.brain.prompt import JSON_REMINDER, JSON_REMINDER_STICKERS

LEAKED = "考试啊\n（照输出格式只输出一个json对象）\n有啥不好意思的\n考试要紧\n好好准备"


def test_a_plain_reply_that_repeats_the_reminder_loses_that_line_only():
    reply = parse_reply(LEAKED)
    assert reply.say == "考试啊\n有啥不好意思的\n考试要紧\n好好准备" and not reply.parsed
    assert clean_say("(照“输出格式”，只输出一个 JSON 对象，say 里放你要说的话)") == ""


def test_the_same_inside_a_json_say_and_the_whole_reminder_with_its_example():
    raw = json.dumps({"say": LEAKED, "mood": "平静"}, ensure_ascii=False)
    assert parse_reply(raw).say == "考试啊\n有啥不好意思的\n考试要紧\n好好准备"
    for reminder in (JSON_REMINDER, JSON_REMINDER_STICKERS):
        assert clean_say(f"好的\n{reminder}") == "好的"


def test_her_own_talk_about_json_or_brackets_is_left_alone():
    assert clean_say("你那个 json 对象解析不出来？") == "你那个 json 对象解析不出来？"
    assert clean_say("（笑）输出格式我也不懂") == "（笑）输出格式我也不懂"
    assert clean_say("好的\n（叹气）\n行吧") == "好的\n（叹气）\n行吧"

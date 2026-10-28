"""Memory v3, blank JSON replies (docs/memory_v3_zh.md §15): with her earlier replies in the
history as plain text, DeepSeek's JSON mode often answered with only spaces, and the plain-text
second try that followed wrote no notes. Now his text line carries a JSON reminder with an example,
a blank reply is asked once more in JSON, and plain text is the last resort. The model is a fake and
everything in here is made up (Springfield)."""

import json
from datetime import datetime, timedelta
from pathlib import Path

from fish.brain import Brain, FakeLLM
from fish.brain.prompt import JSON_REMINDER
from fish.brain.respond import PLAIN_REMINDER, plain_text
from fish.config import Settings
from fish.memory import MemoryStore
from fish.storage import connect

T0 = datetime(2027, 3, 1, 20, 0)
PERSONA = "你是大肥鱼。"
KITE = {"text": "他周末要去Springfield湖边放风筝", "kind": "event", "about": "日常"}


def chat_json(say="嗯。", notes=()) -> str:
    return json.dumps({"say": say, "mood": "平静", "topic": "闲聊", "notes": list(notes), "followups": [],
                       "asked": [], "corrections": []}, ensure_ascii=False)


def make_brain(tmp_path: Path, chat) -> tuple[Brain, object, FakeLLM]:
    def answer(messages, json_mode):
        if "这次和他的聊天结束了" in messages[0]["content"]:
            return json.dumps({"summary": "聊了几句", "gist": "聊了几句", "notes": []}, ensure_ascii=False)
        return chat(messages, json_mode)

    conn = connect(tmp_path / "fish.db")
    settings = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db")
    llm = FakeLLM(answer)
    return Brain(conn, settings, llm, persona_text=PERSONA), conn, llm


def chat_calls(llm: FakeLLM) -> list[tuple[list[dict], bool]]:
    return [(m, j) for m, j in llm.calls if "这次和他的聊天结束了" not in m[0]["content"]]


def test_his_text_line_carries_the_reminder_in_the_prompt_only(tmp_path):
    """The reminder sits at the end of his last message; what is stored, and the earlier turns the
    next prompt replays, are his words alone."""
    brain, conn, llm = make_brain(tmp_path, lambda m, j: chat_json())
    brain.respond("周末去湖边放风筝", now=T0)
    brain.respond("你去不去", now=T0 + timedelta(minutes=1))
    messages, json_mode = chat_calls(llm)[-1]
    assert json_mode and messages[-1] == {"role": "user", "content": f"你去不去\n{JSON_REMINDER}"}
    assert [m["content"] for m in messages[1:-1]] == ["周末去湖边放风筝", "嗯。"]
    stored = [r[0] for r in conn.execute("SELECT text FROM messages WHERE role = 'user' ORDER BY id")]
    assert stored == ["周末去湖边放风筝", "你去不去"]


def test_the_reminder_names_json_and_shows_every_field_she_writes():
    """DeepSeek's JSON mode wants the word json and an example of the object in the prompt."""
    assert "json" in JSON_REMINDER
    example = json.loads(JSON_REMINDER[JSON_REMINDER.index("{"):JSON_REMINDER.rindex("}") + 1])
    assert set(example) == {"say", "mood", "topic", "notes", "followups", "asked", "corrections"}


def test_a_picture_keeps_its_own_reminder_and_gets_no_second_one(tmp_path):
    brain, _, llm = make_brain(tmp_path, lambda m, j: chat_json())
    brain.respond("看我拍的", now=T0, image=b"\x89PNG\r\n\x1a\n" + b"\0" * 16)
    parts = chat_calls(llm)[-1][0][-1]["content"]
    text = next(p["text"] for p in parts if p.get("type") == "text")
    assert "JSON 对象" in text and JSON_REMINDER not in text


def test_a_blank_reply_is_asked_again_in_json_and_his_news_is_still_noted(tmp_path):
    replies = iter(["", chat_json("好呀，带上我", notes=[KITE])])
    brain, conn, llm = make_brain(tmp_path, lambda m, j: next(replies))
    assert brain.respond("周末去湖边放风筝", now=T0) == "好呀，带上我"
    calls = chat_calls(llm)
    assert [j for _, j in calls] == [True, True] and calls[0][0] == calls[1][0]
    assert [m.text for m in MemoryStore(conn).alive()] == [KITE["text"]]
    assert brain.empty_firsts == 1 and brain.fallbacks == []


def test_blank_twice_falls_back_to_plain_text_without_the_json_reminder(tmp_path):
    brain, _, llm = make_brain(tmp_path, lambda m, j: "" if j else "好呀")
    assert brain.respond("周末去湖边放风筝", now=T0) == "好呀"
    calls = chat_calls(llm)
    assert [j for _, j in calls] == [True, True, False]
    plain = calls[2][0][-1]["content"]
    assert plain == f"周末去湖边放风筝\n{PLAIN_REMINDER}" and JSON_REMINDER not in plain
    assert brain.empty_firsts == 1 and brain.fallbacks == [{"raw": "", "finish": None, "retried": True}]


def test_a_reply_cut_short_is_not_blank_and_goes_straight_to_plain_text(tmp_path):
    """Only a blank reply is asked again in JSON; one that wrote something and broke off is kept
    as it was for the checkup to see."""
    brain, _, llm = make_brain(tmp_path, lambda m, j: '{"say": ' if j else "好呀")
    assert brain.respond("在吗", now=T0) == "好呀"
    assert [j for _, j in chat_calls(llm)] == [True, False]
    assert brain.empty_firsts == 0 and brain.fallbacks[0]["raw"] == '{"say": ' and not brain.fallbacks[0]["retried"]


def test_plain_text_leaves_other_messages_and_a_line_without_the_reminder_alone():
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": f"a\n{JSON_REMINDER}"},
                {"role": "assistant", "content": "b"}, {"role": "user", "content": "c"}]
    out = plain_text(messages)
    assert out[:3] == messages[:3] and out[3]["content"] == f"c\n{PLAIN_REMINDER}"
    assert messages[3]["content"] == "c"  # the original is not changed

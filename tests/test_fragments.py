"""Split messages become one turn; she may choose silence."""

import json
from datetime import datetime
from pathlib import Path

from fish.brain import Brain, FakeLLM
from fish.channels import WeChatChannel, WeChatState
from fish.config import Settings
from fish.messages import Incoming, Outgoing
from fish.storage import connect

T = datetime(2026, 10, 27, 12, 0)


def user_msg(mid, text):
    return {"message_id": mid, "from_user_id": "o", "message_type": 1, "context_token": "ctx",
            "item_list": [{"type": 1, "text_item": {"text": text}}]}


class SplitClient:
    """First poll brings a message; the quick peeks bring the rest of his sentence, then nothing."""

    def __init__(self):
        self.polls = []
        self.sent = []
        self.queue = [([user_msg("1", "都是麦当劳这种路上的")], "b1"),
                      ([user_msg("2", "店")], "b2"), ([], "b2"),
                      ([], "b2")]

    def get_updates(self, buf, timeout=45.0):
        self.polls.append(timeout)
        return self.queue.pop(0) if self.queue else ([], buf)

    def send_text(self, to, text, token):
        self.sent.append(text)
        return "m"

    def typing_ticket(self, u, t):
        return ""


def test_fragments_are_answered_as_one_turn(tmp_path: Path):
    client = SplitClient()
    heard = []
    state = WeChatState(bot_token="t", bot_id="b", user_id="o")
    ch = WeChatChannel(client, state, tmp_path / "w.json", sleep=lambda s: None, out=lambda s: None, max_polls=1)
    ch.run(lambda inc: heard.append(inc.text) or Outgoing("哦，路上那些店。"))
    assert heard == ["都是麦当劳这种路上的店"]
    assert client.sent == ["哦，路上那些店。"]
    assert client.polls[0] == 45.0 and client.polls[1:] == [2.5, 2.5]
    assert state.get_updates_buf == "b2" and state.seen_ids == ["1", "2"]


def test_join_fragments_reads_like_one_sentence():
    from fish.channels.wechat import join_fragments

    assert join_fragments(["你", "现在", "看得懂", "我说的", "是", "一句话", "吗"]) == "你现在看得懂我说的是一句话吗"
    assert join_fragments(["你", "现在", "几岁"]) == "你现在几岁"
    assert join_fragments(["今天好累啊，课好多", "晚上吃啥你想好了吗"]) == "今天好累啊，课好多 晚上吃啥你想好了吗"
    assert join_fragments(["我在看", "ME370", "的作业"]) == "我在看 ME370 的作业"
    assert join_fragments(["", " 嗯 ", ""]) == "嗯"


def test_silence_sends_nothing(tmp_path: Path):
    client = SplitClient()
    client.queue = [([user_msg("1", "嗯")], "b1"), ([], "b1")]
    state = WeChatState(bot_token="t", bot_id="b", user_id="o")
    ch = WeChatChannel(client, state, tmp_path / "w.json", sleep=lambda s: None, out=lambda s: None, max_polls=1)
    ch.run(lambda inc: Outgoing(""))
    assert client.sent == []


def test_brain_treats_an_empty_say_as_her_choice(tmp_path: Path):
    llm = FakeLLM([json.dumps({"say": "", "mood": "平静", "topic": "闲聊"})])
    conn = connect(tmp_path / "fish.db")
    brain = Brain(conn, Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db"),
                  llm, persona_text="你是大肥鱼。")
    out = brain.handle(Incoming("嗯"), now=T)
    assert out == Outgoing("") and len(llm.calls) == 1  # no plain-mode retry
    assert [t.role for t in brain.window.recent()] == ["user"]


def test_unparseable_reply_still_retries_in_plain_mode(tmp_path: Path):
    llm = FakeLLM(["", "嗯？"])
    conn = connect(tmp_path / "fish.db")
    brain = Brain(conn, Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db"),
                  llm, persona_text="你是大肥鱼。")
    assert brain.handle(Incoming("在吗"), now=T).text == "嗯？" and len(llm.calls) == 2

"""She speaks first: the rules gate, the triggers, her decision, sending and recording."""

import json
from datetime import datetime, timedelta
from pathlib import Path

from fish.brain import Brain, FakeLLM
from fish.brain.leisure import Leisure
from fish.brain.reach import ReachOut, ReachPolicy
from fish.channels import WeChatChannel, WeChatState
from fish.config import Settings
from fish.memory import MemoryStore, ProspectiveStore, Relationship
from fish.messages import Outgoing
from fish.mood import MoodStore
from fish.storage import connect

NOON = datetime(2026, 10, 28, 12, 0)
PERSONA = "你是大肥鱼。"


def make(tmp_path: Path, llm, **settings):
    conn = connect(tmp_path / "fish.db")
    s = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db", **settings)
    brain = Brain(conn, s, llm, persona_text=PERSONA)
    brain.leisure = Leisure(brain, [], sources=[])  # a tick that does not reach out may be a free moment; no network
    return conn, brain


def he_wrote(brain, when, text="在吗"):
    brain.window.append("user", text, "wechat", None, when)
    Relationship(brain.conn).note_active_day(when)


def deciding(say="看到个候鸟的视频，想起你。", asked=(), shared=()):
    def respond(messages, json_mode):
        if "要不要先给他发条消息" in messages[-1]["content"]:
            return json.dumps({"say": say, "asked": list(asked), "shared": list(shared)}, ensure_ascii=False)
        return json.dumps({"say": "嗯"})
    return FakeLLM(respond)


def test_gate_refuses_for_the_right_reasons(tmp_path):
    conn, brain = make(tmp_path, deciding())
    policy = ReachPolicy(conn)
    assert policy.refused(NOON) == "never met"
    he_wrote(brain, NOON - timedelta(hours=3))
    assert policy.refused(NOON) is None
    assert policy.refused(datetime(2026, 10, 28, 23, 0)) == "night"
    assert policy.refused(NOON - timedelta(hours=2, minutes=30)) == "just talked"
    assert ReachPolicy(conn, enabled=False).refused(NOON) == "off"
    policy.record_considered(NOON)
    assert policy.refused(NOON + timedelta(minutes=30)) == "decided recently"
    assert policy.refused(NOON + timedelta(hours=1)) is None
    policy.record_sent(NOON + timedelta(hours=1), ReachOut("x"))
    assert policy.refused(NOON + timedelta(hours=1, minutes=30)) == "too soon"
    policy.record_sent(NOON + timedelta(hours=2), ReachOut("y"))
    assert policy.refused(NOON + timedelta(hours=3)) is None  # no daily cap (decision 30)
    assert ReachPolicy(conn, max_per_day=2).refused(NOON + timedelta(hours=3)) == "enough today"


def test_nothing_to_say_means_no_model_call(tmp_path):
    llm = deciding()
    conn, brain = make(tmp_path, llm)
    he_wrote(brain, NOON - timedelta(hours=3))
    assert brain.consider_reach_out(NOON) is None
    assert llm.calls == []


def test_she_shares_what_she_saw_and_it_is_recorded_once_sent(tmp_path):
    llm = deciding(shared=(1,))
    conn, brain = make(tmp_path, llm)
    he_wrote(brain, NOON - timedelta(hours=3))
    MemoryStore(conn).add("world", "候鸟飞那么远就为找个能吃饭的地方，这我懂。", importance=4,
                          source="https://sspai.com/post/117180", now=NOON - timedelta(hours=1))
    sent: list[str] = []
    assert brain.tick(lambda text: sent.append(text) or True, now=NOON) is True
    assert sent == ["看到个候鸟的视频，想起你。"]
    prompt = llm.calls[0][0][-1]["content"]
    assert "见闻 #1" in prompt and "他上次找你是 3 小时前" in prompt
    turns = brain.window.recent()
    assert [t.role for t in turns] == ["user", "fish"] and turns[-1].text == sent[0]
    policy = ReachPolicy(conn)
    assert policy.count_today(NOON) == 1 and policy.shared_ids() == {1}
    # the same 见闻 is not offered again
    assert brain.consider_reach_out(NOON + timedelta(hours=7)) is None


def test_a_failed_send_records_nothing(tmp_path):
    conn, brain = make(tmp_path, deciding())
    he_wrote(brain, NOON - timedelta(hours=3))
    ProspectiveStore(conn).add("问他演示怎么样", "2026-10-28", now=NOON - timedelta(days=2))
    assert brain.tick(lambda text: False, now=NOON) is False
    assert [t.role for t in brain.window.recent()] == ["user"]
    assert ReachPolicy(conn).count_today(NOON) == 0
    assert ReachPolicy(conn).refused(NOON + timedelta(minutes=5)) == "decided recently"


def test_due_followup_is_asked_and_closed(tmp_path):
    conn, brain = make(tmp_path, deciding(say="你那个演示完了没", asked=(1,)))
    he_wrote(brain, NOON - timedelta(hours=3))
    f = ProspectiveStore(conn).add("问他演示怎么样", "2026-10-28", now=NOON - timedelta(days=2))
    assert brain.tick(lambda text: True, now=NOON)
    assert ProspectiveStore(conn).get(f.id).status == "asked"


def test_she_may_decide_not_to(tmp_path):
    llm = deciding(say="")
    conn, brain = make(tmp_path, llm)
    he_wrote(brain, NOON - timedelta(hours=20))
    assert brain.consider_reach_out(NOON) is None
    assert len(llm.calls) == 1 and "20 个小时没来找你" in llm.calls[0][0][-1]["content"]
    assert brain.consider_reach_out(NOON + timedelta(minutes=30)) is None and len(llm.calls) == 1


def test_no_reach_out_once_wechat_would_drop_it(tmp_path):
    conn, brain = make(tmp_path, deciding())
    he_wrote(brain, NOON - timedelta(days=3))
    assert ReachPolicy(conn).refused(NOON) == "out of reach"


def test_replies_stay_inside_the_token_quota(tmp_path):
    from fish.channels.wechat import TOKEN_QUOTA

    class Client:
        def __init__(self):
            self.sent = []

        def send_text(self, to, text, token):
            self.sent.append((text, token))
            return "m"

    state = WeChatState(bot_token="t", bot_id="b", user_id="o", context_tokens={"o": "ctx"})
    client = Client()
    ch = WeChatChannel(client, state, tmp_path / "w.json", sleep=lambda s: None, out=lambda s: None)
    ch._spend("ctx", TOKEN_QUOTA - 2)
    ch._send_bubbles("o", "一\n二\n三\n四", "ctx")
    assert [t for t, _ in client.sent] == ["一", "二\n三\n四"]  # the tail merged into the last allowed bubble
    assert ch.push("还在吗") is False and len(client.sent) == 2  # quota spent: nothing more on this token
    assert WeChatState.load(tmp_path / "w.json").token_sends == {"ctx": TOKEN_QUOTA}


def test_boredom_and_anniversary_are_triggers(tmp_path):
    conn, brain = make(tmp_path, deciding(say="无聊。"))
    he_wrote(brain, NOON - timedelta(hours=7))
    mood = MoodStore(conn).load()
    mood.boredom = 80
    MoodStore(conn).save(mood)
    assert brain.consider_reach_out(NOON).text == "无聊。"
    Relationship(conn).set("first_met", "2026-10-22")  # day 7 today
    policy = ReachPolicy(conn)
    assert policy.triggers(NOON, MoodStore(conn).load()).anniversary == 7


def test_wechat_channel_pushes_between_polls(tmp_path):
    class Client:
        def __init__(self):
            self.sent = []
            self.polls = 0

        def get_updates(self, buf):
            self.polls += 1
            return [], "buf"

        def send_text(self, to, text, token):
            self.sent.append((to, text, token))
            return "m"

    state = WeChatState(bot_token="t", bot_id="b", user_id="owner", context_tokens={"owner": "ctx"})
    client = Client()
    ticks = []

    def tick(send):
        ticks.append(1)
        return send("想你了\n吃饭没") if len(ticks) == 1 else False

    ch = WeChatChannel(client, state, tmp_path / "w.json", sleep=lambda s: None, out=lambda s: None,
                       max_polls=2, tick=tick)
    ch.run(lambda inc: Outgoing(inc.text))
    assert client.sent == [("owner", "想你了", "ctx"), ("owner", "吃饭没", "ctx")] and len(ticks) == 2
    assert ch.push("x") is True
    state.context_tokens.clear()
    assert ch.push("x") is False


def test_no_daily_cap_but_she_knows_he_has_not_answered(tmp_path):
    """Decision 30: she sends when she wants to, as often as she wants; each time she is told
    how many of her messages he has not answered yet, and that count clears when he writes."""
    llm = deciding(say="在干嘛")
    conn, brain = make(tmp_path, llm)
    he_wrote(brain, NOON - timedelta(hours=20))
    sent: list[str] = []
    for h in range(4):  # four in one afternoon: more than the old cap of two
        assert brain.tick(lambda text: sent.append(text) or True, now=NOON + timedelta(hours=h)) is True
    assert len(sent) == 4
    prompts = [c[0][-1]["content"] for c in llm.calls if "要不要先给他发条消息" in c[0][-1]["content"]]
    assert "他还没回" not in prompts[0] and "你前面主动发的 3 条他还没回" in prompts[3]
    he_wrote(brain, NOON + timedelta(hours=4))
    assert ReachPolicy(conn).unanswered() == 0

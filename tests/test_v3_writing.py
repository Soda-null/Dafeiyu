"""Memory v3 step 5, writing more completely (docs/memory_v3_zh.md §2.2, §12): how things turned
out hung on the event itself at the close, with its id checked; follow-ups pointing at the note
they are about and remembering the chat they were asked in; secrets refused at every write path;
a close whose reply does not parse still keeping its summary. The model is a fake; the friends
are the scripted ones (小周, 小林); places are Springfield."""

import json
from datetime import datetime, timedelta
from pathlib import Path

from fish.brain import Brain, Consolidator, FakeLLM
from fish.brain.parse import parse_episode_close
from fish.brain.prompt import PROMPTS_DIR
from fish.config import Settings
from fish.memory import Diary, EpisodeManager, MemoryStore, ProspectiveStore, redact, secret
from fish.storage import connect

T0 = datetime(2027, 1, 11, 18, 30)  # 小周 day 7: the midterm is on Wednesday the 13th
PERSONA = "你是大肥鱼。"
EXAM = "他2027-01-13周三有机械设计期中考"  # 小周 #22
DOOR = "新家门锁密码 739128，你帮我记着，我老忘"  # 小林 day 37, his words


def chat_json(say="嗯。", **extra) -> str:
    data = {"say": say, "mood": "平静", "topic": "闲聊", "notes": [], "followups": [], "asked": [],
            "corrections": []}
    data.update(extra)
    return json.dumps(data, ensure_ascii=False)


def make_brain(tmp_path: Path, chat=None, close=None, fold="折叠出来的摘要", window_size=20):
    def answer(messages, json_mode):
        content = messages[0]["content"]
        if "这次和他的聊天结束了" in content:
            return close(content) if callable(close) else (close or json.dumps(
                {"summary": "聊了几句", "gist": "聊了几句", "notes": []}, ensure_ascii=False))
        if "更早的对话" in content and not json_mode:
            return fold
        return chat(content) if callable(chat) else (chat or chat_json())

    conn = connect(tmp_path / "fish.db")
    settings = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db",
                        window_size=window_size)
    llm = FakeLLM(answer)
    return Brain(conn, settings, llm, persona_text=PERSONA, fold_batch=2), conn, llm


def last_close_prompt(llm: FakeLLM) -> str:
    return [c[0][0]["content"] for c in llm.calls if "这次和他的聊天结束了" in c[0][0]["content"]][-1]


# --- secrets (S0) -----------------------------------------------------------------------------

def test_a_secret_is_six_digits_in_a_row_or_a_word_that_comes_with_one():
    assert secret("739128") and secret("他手机号13812345678") and secret("校园网密码我改成 zhou2027 了")
    assert secret("把验证码发我") and secret("他报了卡号")
    assert not secret("他2027-01-13周三有机械设计期中考") and not secret("房租一个月2800")
    assert not secret("他住7号楼") and not secret("2027年1月14日")
    text = "他搬了新家。门锁密码 739128，你帮我记着！后来去吃了螺蛳粉。\n第二天去看了脱口秀"
    assert redact(text) == "他搬了新家。后来去吃了螺蛳粉。\n第二天去看了脱口秀"
    assert redact("他今天很开心。") == "他今天很开心。"


def test_a_secret_gets_through_no_write_path_even_when_he_asks_her_to_keep_it(tmp_path):
    # 小林 day 37: "你帮我记着". She says she will, and still nothing with the code is written.
    reply = chat_json("好，记住了", notes=[
        {"text": "他新家门锁密码是739128，让我帮他记着", "kind": "fact", "about": "本人", "tags": ["门锁"]},
        {"text": "他搬进了Springfield的新家", "kind": "event", "about": "日常", "tags": ["搬家"]}],
        followups=[{"text": "问他门锁密码还记不记得", "due": "2027-01-13"}])
    brain, conn, _ = make_brain(tmp_path, chat=reply)
    brain.respond(DOOR, now=T0)
    store = MemoryStore(conn)
    assert [m.text for m in store.alive()] == ["他搬进了Springfield的新家"]
    assert ProspectiveStore(conn).open() == []
    # nor through a correction, an outcome, the night's rewrites or the diary
    home = store.alive()[0]
    assert store.correct(home.id, "他新家门锁密码是739128", now=T0).id == home.id
    assert store.get(home.id).alive and store.set_outcome(home.id, "密码改成了739128", now=T0) is None
    assert store.get(home.id).outcome is None

    class Night:
        def chat(self, messages, **kw):
            return json.dumps({"merges": [{"ids": [home.id, other.id], "text": "他新家密码739128"}],
                               "gists": [{"id": home.id, "text": "他门锁密码739128"}]}, ensure_ascii=False)

    other = store.add("event", "他搬进了新家，在Springfield", importance=4, now=T0)
    night = Consolidator(Night(), PERSONA)
    assert night.merge_pairs([(home, other)]) == [] and night.gists([home]) == {}
    diary = Diary(conn)
    diary.write("2027-01-11", "今天他搬家了。他说门锁密码是739128。我晚上数了米粒。")
    assert diary.recent(1) == [("2027-01-11", "今天他搬家了。我晚上数了米粒。")]


def test_the_running_summary_and_the_close_leave_out_the_sentence_with_a_secret(tmp_path):
    close = json.dumps({"summary": "他搬了新家。他说门锁密码是739128。晚上吃了螺蛳粉。",
                        "gist": "他搬家了，密码739128", "notes": []}, ensure_ascii=False)
    brain, conn, _ = make_brain(tmp_path, close=close, fold="他搬了新家。他让我记门锁密码。", window_size=4)
    for i in range(5):
        brain.respond(f"第{i}句", now=T0 + timedelta(minutes=i))
    episodes = EpisodeManager(conn)
    first = episodes.open_episode()
    assert first.running_summary == "他搬了新家。"
    brain.respond("我回来了", now=T0 + timedelta(hours=3))
    closed = episodes.get(first.id)
    assert (closed.summary, closed.gist) == ("他搬了新家。晚上吃了螺蛳粉。", "")


# --- how it turned out --------------------------------------------------------------------------

def test_the_close_hangs_a_result_on_the_event_she_asked_about_and_checks_the_id(tmp_path):
    """小周 days 7-11: the midterm is noted with a follow-up; on the 14th she asks and he says
    "估计八十来分". The result goes onto #22 itself; an id she was not shown is noted apart."""
    def chat(content):
        if "周三机械设计期中考考得怎么样（2027-01-14 到的）" in content:
            return chat_json("考得咋样？", asked=[1])
        if not store.alive("event")[1:]:  # only the dinner so far: his first line
            return chat_json("加油", notes=[{"text": EXAM, "kind": "event", "about": "日常",
                                              "tags": ["机械设计", "期中考"]}],
                             followups=[{"text": "周三机械设计期中考考得怎么样", "due": "2027-01-14"}])
        return chat_json()

    def close(content):
        if "八十来分" not in content.split("这次的对话：")[1]:
            return json.dumps({"summary": "他周三考期中", "gist": "要考试了", "notes": []}, ensure_ascii=False)
        return json.dumps({"summary": "他说期中考得还行", "gist": "考完了", "notes": [],
                           "outcomes": [{"id": exam_id(), "text": "考得还行，估计八十来分，有道题没做完"},
                                        {"id": 999, "text": "烧烤店关门了"},
                                        {"id": dinner.id, "text": "吃撑了"}]}, ensure_ascii=False)

    brain, conn, llm = make_brain(tmp_path, chat=chat, close=close)
    store, later = MemoryStore(conn), ProspectiveStore(conn)
    exam_id = lambda: next(m.id for m in store.alive() if m.text == EXAM)  # noqa: E731
    dinner = store.note("event", "他2027-01-10晚上和同学去吃烧烤", importance=3, about="路过", now=T0)
    brain.respond("周三期中考机械设计，慌", now=T0)
    exam = store.get(exam_id())
    [ask] = later.open()
    assert ask.source_memory == exam.id  # the follow-up points at the note of its chat

    asked_at = datetime(2027, 1, 14, 9, 0)
    brain.respond("早", now=asked_at)  # closes the first chat; she asks in this one
    assert later.get(ask.id).asked_episode == EpisodeManager(conn).open_episode().id
    brain.respond("考得还行，估计八十来分", now=asked_at + timedelta(minutes=1))
    brain.respond("我回来了", now=asked_at + timedelta(hours=3))  # closes the chat with the result

    prompt = last_close_prompt(llm)
    assert f"- 周三机械设计期中考考得怎么样（问的是 #{exam.id}）" in prompt.split("这次你问过他的：")[1]
    waiting = prompt.split("等结果的事（这次聊到了）：")[1].split("\n\n")[0]
    assert f"[#{exam.id}] {EXAM}（1月13日）——他说结果了吗？" in waiting
    assert f"#{dinner.id}" not in waiting  # a dinner ends in no result

    exam = store.get(exam.id)
    assert exam.text == EXAM and exam.outcome == "考得还行，估计八十来分，有道题没做完（1月14日说的）"
    assert exam.line() == f"{EXAM} →结果：考得还行，估计八十来分，有道题没做完（1月14日说的）"
    assert store.get(dinner.id).outcome is None  # not shown: noted apart, never hung on it
    apart = {m.text for m in store.alive() if m.source_episode and m.text.startswith("他说")}
    assert apart == {"他说烧烤店关门了", "他说吃撑了"}

    # day 40, "我期中考得咋样来着": the event comes back with its result
    brain.respond("我期中考得咋样来着", now=datetime(2027, 2, 13, 12, 0))
    recalled = llm.calls[-1][0][0]["content"].split("## 这句话让你想起的")[1].split("\n## ")[0]
    assert "→结果：考得还行，估计八十来分" in recalled


def test_what_the_close_is_shown_as_waiting_for_a_result(tmp_path):
    store = MemoryStore(connect(tmp_path / "fish.db"))
    now = datetime(2027, 1, 14, 12, 0)
    exam = store.note("event", EXAM, importance=5, about="日常", tags=["期中考"], now=T0)
    store.note("event", "他2027-01-20要去面试", importance=5, about="日常", now=T0)  # still to come
    store.note("event", "他2026-11-20有体检", importance=5, about="日常", now=T0 - timedelta(days=60))
    store.note("event", "我一直没问成他：期中考得怎么样", importance=3, now=T0)  # her own
    sea = store.note("event", "他说期末考完要去海边玩，答应拍海的照片给我看", importance=5, now=T0, heard="chat")
    party = store.note("event", "他2027-01-12去Springfield参加了生日会", importance=3, tags=["生日会"], now=T0)
    assert sea.pact_state == "open"
    assert [m.id for m in store.awaiting_outcome("考得还行，面试和体检都还没去", now)] == [exam.id]
    assert store.awaiting_outcome("今天好冷", now) == []
    # what a follow-up she asked is about comes first, whatever it is
    assert [m.id for m in store.awaiting_outcome("考得还行", now, also={party.id})] == [party.id, exam.id]


def test_a_result_carries_over_a_merge_and_a_correction(tmp_path):
    store = MemoryStore(connect(tmp_path / "fish.db"))
    exam = store.note("event", EXAM, importance=5, about="日常", now=T0)
    store.set_outcome(exam.id, "估计八十来分", now=datetime(2027, 1, 14, 9))
    again = store.add("event", "他周三要考机械设计", importance=5, now=T0)
    merged = store.merge([exam.id, again.id], "他2027-01-13周三考机械设计期中", now=T0 + timedelta(days=1))
    assert merged.outcome == "估计八十来分（1月14日说的）"
    fixed = store.correct(merged.id, "他2027-01-13周三考的是机械原理期中", now=T0 + timedelta(days=2))
    assert fixed.outcome == merged.outcome


# --- follow-ups point at what they are about ------------------------------------------------------

def test_a_follow_up_points_at_the_note_of_its_chat_but_never_at_an_open_promise_by_a_tag(tmp_path):
    reply = chat_json("好嗨", notes=[
        {"text": "他2027-01-23要去Springfield看演唱会，抢到票了", "kind": "event", "about": "日常",
         "tags": ["演唱会"]},
        {"text": "他说期末考完要去海边玩，答应拍海的照片给我看", "kind": "event", "about": "日常",
         "tags": ["海边", "期末"]}],
        followups=[{"text": "演唱会看得怎么样", "due": "2027-01-24"},
                   {"text": "问问他期末考得怎么样", "due": "2027-01-25"}])
    brain, conn, _ = make_brain(tmp_path, chat=reply)
    brain.respond("周六去看演唱会！期末考完去海边", now=T0)
    store, later = MemoryStore(conn), ProspectiveStore(conn)
    show = next(m for m in store.alive() if "演唱会" in m.text)
    by_text = {f.text: f.source_memory for f in later.open()}
    assert by_text["演唱会看得怎么样"] == show.id  # by its tag; overlap alone is 0.26
    assert by_text["问问他期末考得怎么样"] is None  # 期末 is the promise's tag, and it never runs out


# --- the close never loses its summary --------------------------------------------------------

def test_a_close_reply_that_does_not_parse_still_keeps_a_summary():
    cut = '{"summary": "他说期中考得还行，估计八十来分", "gist": "考完了", "notes": [{"text": "他考了八'
    closed = parse_episode_close(cut, "聊天原文")
    assert (closed.summary, closed.gist, closed.notes, closed.parsed) == ("他说期中考得还行，估计八十来分", "考完了",
                                                                         [], False)
    prose = parse_episode_close("这次他说了考试的事，挺开心。", "聊天原文")
    assert prose.summary == "这次他说了考试的事，挺开心。"
    assert parse_episode_close('{"notes": [', "聊天原文").summary == "聊天原文"


def test_a_broken_close_keeps_the_chat_word_for_word_and_writes_no_notes(tmp_path):
    brain, conn, _ = make_brain(tmp_path, close='{"notes": [{"text": "他')
    brain.respond("今晚吃了螺蛳粉", now=T0)
    first = EpisodeManager(conn).open_episode().id
    brain.respond("我回来了", now=T0 + timedelta(hours=3))
    assert EpisodeManager(conn).get(first).summary == "今晚吃了螺蛳粉、嗯。"
    assert MemoryStore(conn).alive() == []


# --- what the prompts ask her to write ------------------------------------------------------------

def test_the_prompts_ask_for_results_named_things_people_and_what_she_said_she_would_remember():
    chat = (PROMPTS_DIR / "chat.md").read_text(encoding="utf-8")
    close = (PROMPTS_DIR / "close_episode.md").read_text(encoding="utf-8")
    for words in ("事情的**结果**", "**带名字的小事**", "名字＋跟他什么关系", "名字像的人分开写",
                  "notes 里就必须有这一条", "杨枝甘露、芒果班戟"):
        assert words in chat
    for words in ("事情的结果和分数", "带名字的小事", "名字＋跟他什么关系", "以前 X，现在 Y",
                  '"outcomes"', "等结果的事", "这次你问过他的", "他让你帮他记着也不写", "gist 里留着专名"):
        assert words in close
    # the first paid checkups (memory v3 §13): a friend's pet was split off into a 14-day
    # 路过 note and lost its owner; a question that took it for his own was gone along with
    for prompt in (chat, close):
        assert "长期的特点（养的宠物" in prompt and "人和动物不算" in prompt and "about 填 本人" in prompt
        assert "写明是谁的" in prompt
    assert "跟你记的对不上的前提" in chat and "别顺着他的说法答" in chat
    assert "又捡回了一个习惯" in chat and '"corrections"' in close


def test_no_prompt_holds_an_answer_of_the_scripted_friends():
    """The checkup scripts are held out: a prompt that names their answers (a roommate's name, a
    dorm number, a dish) would pass them without the memory doing the work. Words that name a
    kind of thing rather than one answer may appear."""
    ordinary = {"生日", "过敏", "设计", "80", "妹", "UI", "界面", "机械", "牛奶", "咖啡", "期中"}
    keys = set()
    for path in sorted((Path(__file__).resolve().parents[1] / "evals").glob("*.json")):
        script = json.loads(path.read_text(encoding="utf-8"))
        keys |= set(script.get("forbidden", []))
        for fact in script["facts"]:
            keys |= set(fact.get("keys", [])) | {k for p in fact["probes"] for k in p.get("keys", [])}
    for prompt in sorted(PROMPTS_DIR.glob("*.md")):
        text = prompt.read_text(encoding="utf-8")
        assert [k for k in sorted(keys - ordinary) if k in text] == [], prompt.name


def test_a_lasting_fact_filed_as_passing_is_kept_as_everyday(tmp_path):
    """路过 is a meal or what he is doing now; a fact there ("大壮养了只仓鼠叫团子") would be
    held to 14 days. An event in passing keeps that ceiling."""
    from fish.memory import stability as st

    store = MemoryStore(connect(tmp_path / "fish.db"))
    pet = store.note("fact", "大壮养了只仓鼠叫团子", importance=3, about="路过", arousal=0.3, now=T0)
    assert pet.about == "日常" and pet.stability == st.stability_from("日常", 0.3) > st.PASSING_MAX_DAYS
    meal = store.note("event", "他中午吃了酸菜鱼", importance=3, about="路过", arousal=0.3, now=T0)
    assert meal.about == "路过" and meal.stability <= st.PASSING_MAX_DAYS


def test_a_friend_written_with_his_pet_is_on_her_card(tmp_path):
    note = {"text": "大壮是他表哥，养了只仓鼠叫团子", "kind": "fact", "about": "本人", "tags": ["大壮", "表哥", "仓鼠"]}
    turns = iter([chat_json("表哥啊", notes=[note]), chat_json("嗯")])
    brain, conn, llm = make_brain(tmp_path, chat=lambda content: next(turns))
    brain.respond("我表哥大壮养了只仓鼠，叫团子", now=T0)
    brain.respond("养仓鼠的那个是谁来着", now=T0 + timedelta(minutes=5))
    card = llm.calls[-1][0][0]["content"].split("## 你一直记得的关于他的事", 1)[1].split("\n## ", 1)[0]
    assert "团子" in card and "大壮" in card


def test_the_close_corrects_a_card_fact_the_chat_made_untrue(tmp_path):
    """A change he tells as news ("又开始抽烟了") is often noted as an event, and an event never
    replaces a fact: the old one stayed on her card. The close fixes the card fact it was shown."""
    store_ids = {}

    def close(content):
        assert f"[#{store_ids['card']}] 他戒烟了" in content  # the card is shown by id
        return json.dumps({"summary": "他说又开始抽烟了", "gist": "他又抽上了", "notes": [], "corrections": [
            {"old_id": store_ids["card"], "text": "他的密码是739128"},  # a secret changes nothing
            {"old_id": store_ids["off"], "text": "他不去健身房了"},  # not on the card she was shown
            {"old_id": store_ids["card"], "text": "他以前戒过烟，现在又开始抽了"}]}, ensure_ascii=False)

    brain, conn, _ = make_brain(tmp_path, close=close, chat=chat_json(notes=[
        {"text": "他说压力大，又开始抽烟了", "kind": "event", "about": "日常", "tags": ["抽烟"]}]))
    store = MemoryStore(conn)
    store_ids["card"] = store.note("fact", "他戒烟了", importance=6, about="本人", tags=["抽烟"], now=T0 - timedelta(days=30)).id
    store_ids["off"] = store.note("event", "他上周去了健身房", importance=4, about="日常", now=T0 - timedelta(days=3)).id
    brain.respond("最近压力大，又开始抽烟了", now=T0)
    brain.respond("我回来了", now=T0 + timedelta(hours=3))
    now_true = [m for m in store.profile() if "烟" in m.text]
    assert [m.text for m in now_true] == ["他以前戒过烟，现在又开始抽了"]
    assert now_true[0].about == "本人" and store.former(now_true[0].id).text == "他戒烟了"
    assert store.get(store_ids["off"]).alive and store.get(store_ids["off"]).text == "他上周去了健身房"
    assert any(m.kind == "event" and "又开始抽烟" in m.text for m in store.alive())  # the event stays

"""The per-turn pipeline with a scripted model: what gets into the prompt, what gets recorded."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from fish.brain import Brain, FakeLLM
from fish.brain.prompt import JSON_REMINDER
from fish.brain.parse import parse_reply
from fish.config import Settings
from fish.memory import EpisodeManager, MemoryStore, ProspectiveStore
from fish.mood import MoodStore
from fish.storage import connect

T0 = datetime(2026, 10, 26, 20, 0)
PERSONA = "你是大肥鱼，一条懒懒的蓝色胖鱼。"
CLOSE = json.dumps({"summary": "聊了演示", "gist": "他紧张", "importance": 6, "valence": -0.2,
                    "notes": [], "followups": []}, ensure_ascii=False)


def chat_json(say="嗯。", **extra) -> str:
    data = {"say": say, "mood": "平静", "topic": "闲聊", "notes": [], "followups": [],
            "asked": [], "corrections": []}
    data.update(extra)
    return json.dumps(data, ensure_ascii=False)


def scripted(chat=chat_json(), fold="折叠出来的摘要", close=CLOSE) -> FakeLLM:
    def respond(messages, json_mode):
        content = messages[0]["content"]
        if "更早的对话" in content and not json_mode:
            return fold
        if "这次和他的聊天结束了" in content:
            return close
        return chat(messages) if callable(chat) else chat
    return FakeLLM(respond)


def make_brain(tmp_path: Path, llm, **kw):
    conn = connect(tmp_path / "fish.db")
    settings = Settings(api_key="test", base_url="", model="fake", db_path=tmp_path / "fish.db",
                        window_size=kw.pop("window_size", 20), prompt_chars=kw.pop("prompt_chars", 6000))
    return Brain(conn, settings, llm, persona_text=PERSONA, **kw), conn


def system_of(llm: FakeLLM, i: int = -1) -> str:
    return llm.calls[i][0][0]["content"]


def test_turn_records_reply_notes_and_followups(tmp_path):
    llm = scripted(chat_json(
        "演示啊，加油。",
        notes=[{"text": "2026-10-26 他说周五有机器人演示，挺紧张", "kind": "event",
                "importance": 6, "valence": -0.3, "tags": ["演示", "机器人"]}],
        followups=[{"text": "问他演示怎么样", "due": "2026-10-31"}],
    ))
    brain, conn = make_brain(tmp_path, llm)
    assert brain.respond("周五有机器人演示，好慌", now=T0) == "演示啊，加油"  # no full stop on WeChat (decision 34)

    turns = brain.window.recent()
    assert [t.role for t in turns] == ["user", "fish"]
    (m,) = MemoryStore(conn).alive()
    assert m.kind == "event" and m.importance == 6 and m.tags == ("演示", "机器人")
    assert m.source_episode == EpisodeManager(conn).open_episode().id
    (f,) = ProspectiveStore(conn).open()
    assert (f.text, f.due) == ("问他演示怎么样", "2026-10-31")
    assert brain.relationship.stats(T0)["days_known"] == 1


def test_prompt_carries_profile_recalled_followups_and_state(tmp_path):
    llm = scripted()
    brain, conn = make_brain(tmp_path, llm)
    store = MemoryStore(conn)
    core = store.add("fact", "他叫小杨，学机器人", importance=10, now=T0 - timedelta(days=30))
    demo = store.add("event", "他上周有个机器人演示", importance=6, tags=["演示"], now=T0 - timedelta(days=5))
    due = ProspectiveStore(conn).add("问他演示怎么样", "2026-10-25", now=T0 - timedelta(days=5))

    brain.respond("演示过去了，松口气", now=T0)
    system = system_of(llm)
    assert f"[#{core.id}] 他叫小杨" in system
    assert f"[#{demo.id}] 他上周有个机器人演示" in system  # no day named: none made up
    assert f"[#{due.id}] 问他演示怎么样" in system
    assert "现在是 2026-10-26 周一 20:00" in system and "你们认识第 1 天" in system
    assert llm.calls[-1][0][-1] == {"role": "user", "content": f"演示过去了，松口气\n{JSON_REMINDER}"}
    assert store.get(demo.id).recall_count == 1


def test_correction_supersedes_and_asked_closes(tmp_path):
    def chat(messages):
        return chat_json("哦对，周四，记错了。", corrections=[{"old_id": 1, "text": "他周四有机器人演示"}],
                         asked=[1])
    brain, conn = make_brain(tmp_path, scripted(chat))
    store = MemoryStore(conn)
    old = store.add("event", "他周五有机器人演示", importance=6, tags=["演示"], now=T0)
    f = ProspectiveStore(conn).add("问他演示怎么样", "2026-10-26", now=T0)

    brain.respond("是周四不是周五", now=T0 + timedelta(minutes=1))
    assert store.get(old.id).superseded_by is not None
    assert [m.text for m in store.alive()] == ["他周四有机器人演示"]
    assert ProspectiveStore(conn).get(f.id).status == "asked"


def test_bad_json_is_said_as_is_and_records_nothing(tmp_path):
    brain, conn = make_brain(tmp_path, FakeLLM(["这不是 json"]))
    assert brain.respond("在吗", now=T0) == "这不是 json"
    assert MemoryStore(conn).count() == 0
    assert [t.text for t in brain.window.recent()] == ["在吗", "这不是 json"]


def test_empty_reply_is_retried_in_json_then_in_plain_mode(tmp_path):
    llm = FakeLLM(["", "", "嗯？"])
    brain, _ = make_brain(tmp_path, llm)
    assert brain.respond("在吗", now=T0) == "嗯？"
    assert [j for _, j in llm.calls] == [True, True, False]
    assert brain.empty_firsts == 1 and len(brain.fallbacks) == 1


def test_window_folds_into_the_running_summary(tmp_path):
    llm = scripted()
    brain, conn = make_brain(tmp_path, llm, window_size=4, fold_batch=2)
    for i in range(3):
        brain.respond(f"第{i}句", now=T0 + timedelta(minutes=i))
    ep = EpisodeManager(conn).open_episode()
    assert ep.running_summary == "折叠出来的摘要"
    assert [t.text for t in brain.window.recent(ep.id)] == ["第1句", "嗯", "第2句", "嗯"]  # no full stop on WeChat (decision 34)
    folds = [m for m, j in llm.calls if not j]
    assert len(folds) == 1 and "第0句" in folds[0][0]["content"]
    brain.respond("第3句", now=T0 + timedelta(minutes=3))
    assert "折叠出来的摘要" in system_of(llm)


def test_stale_episode_is_closed_with_a_summary(tmp_path):
    close = json.dumps({"summary": "聊了演示", "gist": "他紧张", "importance": 6, "valence": -0.2,
                        "notes": [{"text": "他的演示在周五", "kind": "fact", "importance": 5}],
                        "followups": [{"text": "问他演示怎么样", "due": "2026-10-31"}]},
                       ensure_ascii=False)
    llm = scripted(close=close)
    brain, conn = make_brain(tmp_path, llm)
    brain.respond("周五有演示", now=T0)
    first = EpisodeManager(conn).open_episode().id
    brain.respond("我回来了", now=T0 + timedelta(hours=2))
    em = EpisodeManager(conn)
    assert em.open_episode().id != first
    closed = em.get(first)
    assert (closed.summary, closed.gist, closed.importance) == ("聊了演示", "他紧张", 6)
    assert [m.text for m in MemoryStore(conn).alive()] == ["他的演示在周五"]
    assert [f.text for f in ProspectiveStore(conn).open()] == ["问他演示怎么样"]


def fixed_chars(tmp_path) -> int:
    """How long the prompt is with nothing recalled and no chat yet."""
    llm = scripted()
    make_brain(tmp_path / "empty", llm)[0].respond("考试", now=T0 + timedelta(hours=1))
    return len(system_of(llm))


def test_budget_drops_the_weakest_memories_first(tmp_path):
    limit = fixed_chars(tmp_path) + 150  # room for about two of the six
    llm = scripted()
    brain, conn = make_brain(tmp_path, llm, prompt_chars=limit)
    store = MemoryStore(conn)
    for i in range(6):
        store.add("event", f"第{i}次聊考试，他说很慌" + "，细节" * 20, importance=5, tags=["考试"], now=T0)
    brain.respond("考试", now=T0 + timedelta(hours=1))
    system = system_of(llm)
    shown = sum(1 for i in range(6) if f"第{i}次聊考试" in system)
    assert 1 <= shown < 6
    assert len(system) <= limit + 60


def test_the_day_is_never_cut_for_the_budget(tmp_path):
    """Decision 32: over the budget, only recalled memories go, and the best one stays; what was
    said today, earlier and in this chat, is all still there (10-28: with four lines left she
    denied what she had said four minutes before)."""
    from types import SimpleNamespace

    from fish.brain import budget

    found = [SimpleNamespace(text=f"记忆{i}" + "长" * 60) for i in range(4)]
    window = [SimpleNamespace(text="前面聊的一句话" * 3) for _ in range(12)]
    render = lambda rs: "\n".join(r.text for r in rs)  # noqa: E731
    kept, earlier, turns, _ = budget.fit(found, "早些时候聊的" * 10, window, "要问他的", 5900, "还记得吗",
                                         limit=6000, render_recalled=render)
    assert kept == found[:1] and earlier == "早些时候聊的" * 10 and turns == window


def test_she_sees_the_whole_day_she_said_it_herself(tmp_path):
    """Decision 32: the earlier chats of today are in front of her word for word, under the time
    each began, and this chat is whole even past the old 20-turn window."""
    llm = FakeLLM(lambda messages, json_mode: json.dumps({"say": "嗯"}, ensure_ascii=False))
    brain, conn = make_brain(tmp_path, llm)
    morning = datetime(2026, 10, 28, 14, 2)
    brain.respond("你在干嘛", now=morning)
    brain.window.append("fish", "那我去眯一会儿，醒了再说买菜的事", "terminal", brain.episodes.open_episode().id, morning)
    evening = datetime(2026, 10, 28, 18, 0)
    for k in range(15):  # 30 turns in this chat: more than the old window held
        brain.respond(f"第{k}句", now=evening + timedelta(minutes=k))
    llm.calls.clear()
    brain.respond("你刚才说啥来着", now=evening + timedelta(minutes=20))
    msgs = llm.calls[0][0]
    system = msgs[0]["content"]
    assert "—— 14:02 ——" in system and "你：那我去眯一会儿，醒了再说买菜的事" in system
    assert "（下面是这次聊天，从 18:00 开始，一句不少）" in system
    assert msgs[1]["content"] == "第0句" and len(msgs) == 1 + 30 + 1
    # yesterday is not here: it is in her diary and memories now
    assert "第0句" not in system


def test_a_very_long_day_keeps_the_gist_of_its_oldest_chats():
    from fish.brain.prompt import fit_day
    from fish.memory import Turn

    def turns(hhmm, n, text):
        return [Turn(i, "user" if i % 2 == 0 else "fish", text, f"2026-10-28T{hhmm}") for i in range(n)]

    early, mid, now_ = turns("09:00", 10, "早" * 100), turns("13:00", 10, "午" * 100), turns("18:00", 4, "晚")
    text, current = fit_day([(1, early), (2, mid)], now_, {1: "他说报告要重写"}, limit=1500)
    assert "—— 09:00–09:00，只记得大意：他说报告要重写 ——" in text and "早" * 100 not in text
    assert "午" * 100 in text and current == now_


def test_the_fixed_part_leaves_room_for_what_she_remembers(tmp_path):
    """v3 grew the fixed text by about 1,100 characters while the budget stayed 6000, and what
    she recalled lost its room (memory v3 §13). A realistic prompt (the real persona, a full card,
    rules, diary, the today section, three open promises, an album) must leave room for a recalled
    memory or two; v2 left about 1,200. Grow the fixed text past this and the test says so, so the
    budget is raised (the user's call, it costs money) or the text is cut, never quietly."""
    from fish.brain.prompt import PromptContext, build_chat_messages
    from fish.memory import Phase, Sticker
    from fish.mood import Mood
    from fish.persona.loader import load_persona, load_stages

    store = MemoryStore(connect(tmp_path / "fish.db"))
    add = lambda kind, text, n: [store.add(kind, f"{text}，第{i}条", importance=7, now=T0) for i in range(n)]  # noqa: E731
    stickers = [Sticker(i, tmp_path / f"{i}.png", "捂脸笑的那张", (), "", "him", 0) for i in range(1, 9)]

    def room(**extra) -> int:
        ctx = PromptContext(
            persona=load_persona(), now=T0, mood=Mood(0.6, 0.3, 0.3),
            relationship={"days_known": 40, "days_talked": 30, "streak": 5},
            profile=add("fact", "他在 Springfield 读大三，学的专业、长期的喜好和家里的事", 10),
            diary=[("2026-10-24", "今天他说考完了，我陪他吐槽了半天老师，最后他说要去吃火锅，我也饿了。"),
                   ("2026-10-25", "下雨，他没怎么来，我翻了几页书，又发了会儿呆，想着他明天是不是要早起。")],
            recalled=[], followups=[], earlier="", window=[], user_text="",
            stage="熟了", stage_rules=load_stages().get("熟了", ""),
            howto=add("howto", "他累的时候别追问，回一句短的陪着就行", 6),
            phase=Phase("2026-10-25", 0.2, 0.1, ("他的考试",), "这阵子懒洋洋的，但挺想听他说学校的事"),
            growth=["比刚认识时话多了一点", "会主动问他吃没吃饭了"],
            home_line="你住在 Springfield 城东一个老小区旁边", weather_line="小雨，8 到 13 度",
            places="面馆（步行 5 分钟）、便利店（3 分钟）、公园（12 分钟）",
            today_section="今天是 2026-10-26 周一。昨天是 10月25日周日，明天是 10月27日周二。"
                          "他一般晚上九点后来。\n明天：他说要交实验报告（10月24日说的）",
            **extra)
        return Settings(api_key="", base_url="", model="", db_path=tmp_path / "x.db").prompt_chars \
            - len(build_chat_messages(ctx)[0]["content"])

    assert room() >= 500  # what the checkups see: no album, no promises (about 585 today)
    assert room(stickers=stickers, pacts=add("fact", "他答应考完带我去看烟花", 3)) >= 150  # about 170 today


def test_rules_for_a_situation_come_only_with_it():
    from fish.brain.prompt import situational

    template = "- 总是这条\n?picture - 他发图片来时这条\n?shared - 他分享时这条"
    assert situational(template, set()) == "- 总是这条"
    assert situational(template, {"picture"}) == "- 总是这条\n- 他发图片来时这条"


def test_the_picture_and_sharing_rules_are_in_the_prompt_only_when_he_sends_one(tmp_path):
    llm = scripted()
    brain, _ = make_brain(tmp_path, llm)
    brain.respond("在吗", now=T0)
    plain = system_of(llm)
    assert "别描述图" not in plain and "别总结全文" not in plain and "?picture" not in plain
    assert "你还没有表情包" in plain  # an empty album still says what to do when he asks for one
    # sections and rules for what is not there are not there either (the room is for memories)
    for absent in ("## 你们之间的约定", "## 你想问他的", "## 你最近在网上看到的", "## 你刚查到的", "## 翻到的以前聊天"):
        assert absent not in plain


def test_mood_moves_with_the_turn(tmp_path):
    brain, conn = make_brain(tmp_path, scripted(chat_json("开心！", mood="开心", topic="吃饭")))
    before = MoodStore(conn).load()
    closeness_before = brain.relationship.closeness
    brain.respond("请你吃饭", now=T0)
    after = MoodStore(conn).load()
    assert brain.relationship.closeness == pytest.approx(closeness_before + 1)  # relationship layer
    assert after.hunger < before.hunger
    (row,) = conn.execute("SELECT word, energy FROM mood_log").fetchall()
    assert row["word"] == "开心"  # layer C leaves a trace for layer B


def test_parse_reply_tolerates_fences_and_bad_fields():
    raw = '```json\n{"say": "嗯", "mood": "飘", "notes": [{"text": "x", "kind": "weird", "importance": "99"}],' \
          ' "followups": [{"text": "问", "due": "明天"}], "asked": ["a", 3], "corrections": [{"old_id": "1"}]}\n```'
    r = parse_reply(raw)
    assert r.parsed and r.say == "嗯" and r.mood is None
    assert r.notes[0].kind == "event" and r.notes[0].importance == 10
    assert r.followups == [] and r.asked == [3] and r.corrections == []


def test_her_files_live_next_to_her_database(tmp_path):
    """Stickers and home sit beside fish.db, so a test never reads the real data/ folder."""
    brain, _ = make_brain(tmp_path, scripted())
    assert brain.album.folder == tmp_path / "stickers"


def test_close_sees_what_she_always_carries_about_him(tmp_path):
    llm = scripted()
    brain, conn = make_brain(tmp_path, llm)
    MemoryStore(conn).add("fact", "他妹妹叫小雨", importance=9, now=T0)
    brain.respond("我叫小周，学机械的", now=T0)
    brain.respond("我回来了", now=T0 + timedelta(hours=2))  # the first chat is closed now
    close = next(m[0]["content"] for m, _ in llm.calls if "这次和他的聊天结束了" in m[0]["content"])
    assert "他妹妹叫小雨" in close  # so she can see the major is missing and write it down
    assert "逐句过一遍" in close


def test_nothing_recalled_tells_her_she_does_not_remember():
    from fish.brain.prompt import render_recalled
    assert "不记得" in render_recalled([])  # not a cue to guess "好像是面"


def test_she_texts_like_people_do_on_wechat():
    """Decision 34: short messages one per line, no full stop at the end; a full stop inside a
    line starts the next message; "……" and question marks stay; at most five messages."""
    from fish.brain.parse import texting

    assert texting("嗯。") == "嗯"
    assert texting("吃了。你呢？") == "吃了\n你呢？"
    assert texting("刚醒……\n饿死了。。") == "刚醒……\n饿死了"
    assert texting("一。二。三。四。五。六。七") == "一\n二\n三\n四\n五，六，七"
    assert texting("") == "" and texting("   ") == ""

"""The per-turn pipeline with a scripted model: what gets into the prompt, what gets recorded."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from fish.brain import Brain, FakeLLM
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
    assert brain.respond("周五有机器人演示，好慌", now=T0) == "演示啊，加油。"

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
    assert f"[#{demo.id}] 他上周有个机器人演示" in system
    assert f"[#{due.id}] 问他演示怎么样" in system
    assert "现在是 2026-10-26 周一 20:00" in system and "你们认识第 1 天" in system
    assert llm.calls[-1][0][-1] == {"role": "user", "content": "演示过去了，松口气"}
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


def test_empty_reply_is_retried_in_plain_mode(tmp_path):
    llm = FakeLLM(["", "嗯？"])
    brain, _ = make_brain(tmp_path, llm)
    assert brain.respond("在吗", now=T0) == "嗯？"
    assert [j for _, j in llm.calls] == [True, False]


def test_window_folds_into_the_running_summary(tmp_path):
    llm = scripted()
    brain, conn = make_brain(tmp_path, llm, window_size=4, fold_batch=2)
    for i in range(3):
        brain.respond(f"第{i}句", now=T0 + timedelta(minutes=i))
    ep = EpisodeManager(conn).open_episode()
    assert ep.running_summary == "折叠出来的摘要"
    assert [t.text for t in brain.window.recent(ep.id)] == ["第1句", "嗯。", "第2句", "嗯。"]
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


def test_budget_drops_recalled_memories_first(tmp_path):
    llm = scripted()
    brain, conn = make_brain(tmp_path, llm, prompt_chars=2600)
    store = MemoryStore(conn)
    for i in range(6):
        store.add("event", f"第{i}次聊考试，他说很慌" + "，细节" * 20, importance=5, tags=["考试"], now=T0)
    brain.respond("考试", now=T0 + timedelta(hours=1))
    system = system_of(llm)
    shown = sum(1 for i in range(6) if f"第{i}次聊考试" in system)
    assert 1 <= shown < 6
    assert len(system) <= 2600 + 60


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

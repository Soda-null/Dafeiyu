"""What slowly changes (decision 11): closeness stages, the how-to-get-along card, her recent line."""

import json
from datetime import datetime, timedelta
from pathlib import Path

from fish.brain import Brain, FakeLLM
from fish.config import PERSONA_PATH, Settings
from fish.memory import Diary, EpisodeManager, MemoryStore, PhaseStore, Relationship
from fish.mood import Mood, MoodStore, stage_of
from fish.persona import load_persona, load_stages, split_persona
from fish.routines import run_nightly
from fish.storage import connect

NIGHT = datetime(2026, 10, 27, 3, 30)
PERSONA = """# 她

> **地位：** 现行

## 性格
- 懒。

## 和他的熟悉程度（亲近值到了就换一档）

### 刚认识（亲近 0–24）
- 话少。

### 熟了（亲近 25–59）
- 会损他。

### 很熟（亲近 60 以上）
- 想说什么说什么。

## 底线
- 不编。
"""


def test_persona_splits_into_base_and_stages():
    base, stages = split_persona(PERSONA)
    assert "## 性格" in base and "## 底线" in base and "熟悉程度" not in base and "地位" not in base
    assert stages == {"刚认识": "- 话少。", "熟了": "- 会损他。", "很熟": "- 想说什么说什么。"}


def test_the_real_persona_file_has_all_three_stages():
    assert set(load_stages(PERSONA_PATH)) == {"刚认识", "熟了", "很熟"}
    assert "熟悉程度" not in load_persona(PERSONA_PATH)


def test_stage_thresholds_and_description():
    assert [stage_of(c) for c in (0, 24.9, 25, 59.9, 60, 100)] == ["刚认识", "刚认识", "熟了", "熟了", "很熟", "很熟"]
    assert "和他熟了" in Mood(70, 20, 40).describe("熟了")
    assert "和他刚认识" in Mood(70, 20, 40).describe("刚认识")


def make(tmp_path: Path, llm):
    conn = connect(tmp_path / "fish.db")
    settings = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db")
    _, stages = split_persona(PERSONA)
    return conn, Brain(conn, settings, llm, persona_text="你是大肥鱼。", stages=stages)


def test_prompt_carries_the_current_stage_rules_howto_and_recent_line(tmp_path):
    llm = FakeLLM([json.dumps({"say": "嗯"}), json.dumps({"say": "嗯"})])
    conn, brain = make(tmp_path, llm)
    MemoryStore(conn).add("howto", "他喜欢被损，别客气", importance=7, now=NIGHT)
    PhaseStore(conn).update("2026-10-26", tone_today=0.8, drive_today=0.9, focus=["候鸟"], line="最近迷上看候鸟")
    brain.respond("在吗", now=NIGHT + timedelta(hours=9))
    system = llm.calls[0][0][0]["content"]
    assert "熟悉程度：刚认识" in system and "- 话少。" in system and "会损他" not in system
    assert "[#1] 他喜欢被损，别客气" in system and "最近迷上看候鸟" in system and "在意的：候鸟" in system
    Relationship(conn).set_closeness(70)
    brain.respond("还在吗", now=NIGHT + timedelta(hours=9, minutes=1))
    system = llm.calls[1][0][0]["content"]
    assert "熟悉程度：很熟" in system and "想说什么说什么" in system and "- 话少。" not in system


def nightly_llm():
    def respond(messages, json_mode):
        content = messages[-1]["content"]
        if "想看出点规律" in content:
            assert "你已经总结过的相处方式" in content
            return json.dumps({"insights": [{"text": "他老是半夜来", "importance": 7}],
                               "howto": [{"text": "他说“笑死”就是真的开心", "importance": 7},
                                         {"text": "别问他学习", "importance": 6}]}, ensure_ascii=False)
        if "你在写日记" in content:
            return json.dumps({"diary": "数米粒。", "self_notes": [], "phase_line": "最近老想换鱼缸"}, ensure_ascii=False)
        if "这次和他的聊天结束了" in content:
            return json.dumps({"summary": "s", "gist": "g", "importance": 4, "valence": 0, "notes": [], "followups": []})
        return json.dumps({"say": "嗯"})
    return FakeLLM(respond)


def test_reflection_grows_the_howto_card_and_diary_sets_the_recent_line(tmp_path):
    conn, brain = make(tmp_path, nightly_llm())
    em = EpisodeManager(conn)
    for i in range(5):
        start = datetime(2026, 10, 22 + (i % 4), 20, i)
        brain.window.append("user", f"第{i}句", "wechat", None, start)
        ep = em.start("wechat", start)
        em.close(ep.id, summary="s", gist=f"第{i}次", importance=4, valence=0, now=start + timedelta(minutes=5))
    report = run_nightly(conn, NIGHT, brain=brain)
    assert report["howto"] == 2 and report["diary"] is True
    store = MemoryStore(conn)
    assert [m.text for m in store.howto_card()] == ["他说“笑死”就是真的开心", "别问他学习"]
    assert PhaseStore(conn).current().line == "最近老想换鱼缸"
    assert Diary(conn).recent(1) == [("2026-10-26", "数米粒。")]


def test_closeness_decays_only_on_a_day_without_him(tmp_path):
    conn, brain = make(tmp_path, nightly_llm())
    brain.window.append("user", "你好", "wechat", None, datetime(2026, 10, 24, 12, 0))
    rel = Relationship(conn)
    rel.set_closeness(30)
    run_nightly(conn, datetime(2026, 10, 25, 3, 30), brain=brain)  # closes 10-24: they talked
    assert rel.closeness == 30
    run_nightly(conn, datetime(2026, 10, 26, 3, 30), brain=brain)  # closes 10-25: silence
    assert rel.closeness == 29



def test_owner_can_be_she(monkeypatch):
    """FISH_OWNER=她: her prompts and persona call the user 她; 其他 is left alone."""
    from fish.brain.prompt import load_template

    assert "他" in load_template("reflect")
    monkeypatch.setenv("FISH_OWNER", "她")
    assert "他" not in load_template("reflect").replace("其他", "")
    assert "她是你唯一认真聊的人" in load_persona()
    assert "他" not in "".join(load_stages().values()).replace("其他", "")

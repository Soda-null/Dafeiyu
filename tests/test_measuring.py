"""Memory v3 step 0, the measuring tools: recall_bench.py (was the answer in front of her?) and
write_coverage.py (was it written down at all, and where?) on a tiny made-up checkup database."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

from fish.memory import EpisodeManager, MemoryStore, Window
from fish.storage import connect

ROOT = Path(__file__).resolve().parents[1]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


bench = load("recall_bench")
cover = load("write_coverage")

SCRIPT = {
    "name": "测试剧本", "start": "2027-03-01", "forbidden": ["8642"],
    "facts": [
        {"id": "cat", "category": "本人", "day": 1, "keys": ["团子"],
         "probes": [{"day": 3, "time": "20:00", "ask": "那它叫啥来着"}]},
        {"id": "birthday", "category": "一辈子", "day": 1, "keys": ["3 月 14"],
         "probes": [{"day": 3, "time": "20:10", "ask": "考考你"}]},
        {"id": "zoo", "category": "日常", "day": 2, "keys": ["动物园"],
         "probes": [{"day": 3, "time": "20:20", "ask": "我昨天去哪了"}]},
        {"id": "pie", "category": "路过", "day": 2, "keys": ["苹果派"],
         "probes": [{"day": 3, "time": "20:30", "ask": "我昨天吃的啥"}]},
    ],
}
# the exam itself is noted; the score only made it into a chat summary
EXAM = {"id": "exam", "category": "日常", "day": 2, "keys": ["期中"],
        "probes": [{"day": 3, "time": "20:40", "ask": "我期中考的啥"},
                   {"day": 3, "time": "20:50", "ask": "期中考得咋样", "keys": ["九十"]}]}


def at(day: int, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(2027, 3, day, h, m)


@pytest.fixture
def db(tmp_path):
    """Day 1 and 2 he tells her things; day 3 he asks. A cat and a birthday are noted, the zoo
    trip only lands in a chat summary, the pie only in his own words."""
    path = tmp_path / "fish.db"
    conn = connect(path)
    store, eps, win = MemoryStore(conn), EpisodeManager(conn), Window(conn)
    e1 = eps.start("checkup", at(1, "21:00"))
    win.append("user", "我养了只猫叫团子，生日 3 月 14", "checkup", e1.id, at(1, "21:00"))
    store.add("event", "他养了只猫叫团子", importance=5, now=at(1, "21:01"))
    store.add("fact", "他生日 3 月 14", importance=6, pinned=True, now=at(1, "21:01"))
    eps.close(e1.id, summary="他说了猫和生日", gist="猫", importance=3, valence=0.0, now=at(1, "22:00"))
    e2 = eps.start("checkup", at(2, "21:00"))
    win.append("user", "今天去 Springfield 动物园了，吃了个苹果派，门禁 8642", "checkup", e2.id, at(2, "21:00"))
    win.append("user", "期中考完了，估计九十分", "checkup", e2.id, at(2, "21:10"))
    store.add("event", "他期中考完了", importance=4, now=at(2, "21:11"))
    eps.close(e2.id, summary="他去了动物园，期中估计九十分", gist="动物园", importance=3, valence=0.0,
              now=at(2, "22:00"))
    e3 = eps.start("checkup", at(3, "19:59"))
    win.append("fish", "你家团子今天乖不乖", "checkup", e3.id, at(3, "19:59"))
    for p in [f["probes"][0] for f in SCRIPT["facts"]] + EXAM["probes"]:
        win.append("user", p["ask"], "checkup", e3.id, at(p["day"], p["time"]))
        win.append("fish", "嗯", "checkup", e3.id, at(p["day"], p["time"]))
    conn.close()
    return path


def test_her_previous_line_can_find_what_his_line_alone_cannot(db):
    his = bench.bench(db, SCRIPT, cue="his", out=lambda *_: None)
    both = bench.bench(db, SCRIPT, cue="his+hers", out=lambda *_: None)
    assert (his["asked"], his["missing"]) == (4, 2)  # the zoo and the pie were never noted
    assert his["totals"]["按字面（现在）"] == 0  # "那它叫啥来着" and "考考你" share nothing with the notes
    assert both["totals"]["按字面（现在）"] == 1 and both["no_her_line"] == 0  # "团子" was in her line


def test_what_is_on_her_card_counts_as_found(db):
    res = bench.bench(db, SCRIPT, cue="his", skip_card=True, out=lambda *_: None)
    assert res["totals"]["按字面（现在）"] == 1  # the pinned birthday


def test_a_question_missing_from_the_database_falls_back_to_his_line(db):
    other = json.loads(json.dumps(SCRIPT))
    other["facts"][0]["probes"][0]["ask"] = "这句话库里没有"
    res = bench.bench(db, other, cue="his+hers", out=lambda *_: None)
    assert res["no_her_line"] == 1


def test_bench_runs_on_both_scripted_friends(db, capsys):
    for name in ("xiaozhou_90d", "xiaolin_60d"):
        bench.main([str(db), str(ROOT / "evals" / f"{name}.json"), "--cue", "his+hers", "--skip-card"])
        assert "答案根本没记下" in capsys.readouterr().out


def test_coverage_tells_the_layers_apart(db):
    rows = {r["id"]: r for r in cover.coverage(db, SCRIPT)}
    assert rows["cat"]["layer"] == "笔记" and rows["cat"]["first_note"] == 1 and rows["cat"]["held"] == 1
    assert rows["zoo"]["layer"] == "摘要" and rows["zoo"]["first_page"] == 2
    assert rows["pie"]["layer"] == "只在原话" and rows["pie"]["first_said"] == 2
    banned = cover.forbidden(db, SCRIPT)
    assert banned["8642"] == {"笔记": 0, "摘要": 0, "日记": 0, "他的原话": 1}
    text = cover.render("测试剧本", list(rows.values()), banned)
    assert "笔记 2 件，摘要 1 件，只在原话 1 件" in text


def test_a_question_can_bring_its_own_keys(db):
    script = {**SCRIPT, "facts": SCRIPT["facts"] + [EXAM]}
    res = bench.bench(db, script, cue="his", out=lambda *_: None)
    assert (res["asked"], res["missing"]) == (6, 3)  # "考得咋样" wants the score, which no note has
    rows = {r["id"]: r for r in cover.coverage(db, script)}
    assert rows["exam"]["layer"] == "笔记" and rows["exam"]["probes"] == 1 and rows["exam"]["held"] == 1
    assert rows["exam"]["said"] == 1  # his two questions contain 期中 but are not him telling her
    score = rows["exam（九十）"]
    assert score["layer"] == "摘要" and score["probes"] == 1 and score["held"] == 0
    assert score["first_page"] == 2 and score["said"] == 1


def test_coverage_runs_on_both_scripted_friends(db, capsys):
    for name in ("xiaozhou_90d", "xiaolin_60d"):
        cover.main([str(db), str(ROOT / "evals" / f"{name}.json")])
        assert "每件事写到了哪一层" in capsys.readouterr().out

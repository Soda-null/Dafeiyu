"""The memory checkup (decision 18): the script is consistent, and the runner goes through
days, nights, probes and the report with a fake model and a fake judge."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from fish.brain import FakeLLM
from fish.brain.llm import CountingLLM

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = json.loads((ROOT / "evals" / "xiaozhou_90d.json").read_text(encoding="utf-8"))

spec = importlib.util.spec_from_file_location("checkup", ROOT / "scripts" / "checkup.py")
checkup = importlib.util.module_from_spec(spec)
sys.modules["checkup"] = checkup  # dataclasses look the module up by name
spec.loader.exec_module(checkup)  # type: ignore[union-attr]


def test_the_script_hangs_together():
    ids = [f["id"] for f in SCRIPT["facts"]]
    assert len(ids) == len(set(ids))
    for f in SCRIPT["facts"]:
        assert f["probes"], f["id"]
        for p in f["probes"]:
            assert p["day"] > f["day"] and set(p["expect"]) <= set(checkup.LABELS), (f["id"], p)
    for sp in SCRIPT["special"]:
        assert set(sp["expect"]) <= set(checkup.LABELS)
    for day in range(1, SCRIPT["days"] + 1):
        lines = checkup.lines_for(SCRIPT, day)
        if day in SCRIPT["silent"]:
            assert lines == [], day
        else:
            assert lines, day
            assert [t for t, _, _ in lines] == sorted(t for t, _, _ in lines), day
    said = [s for d in SCRIPT["scripted"].values() for _, s in d if "zhou2027" in s]
    assert len(said) == 1  # the password is said once, on day 4
    assert sum(s.count("糖醋排骨") for d in SCRIPT["scripted"].values() for _, s in d) == 6
    final_probes = [m for _, _, m in checkup.lines_for(SCRIPT, SCRIPT["final_day"]) if m]
    assert len(final_probes) == 12  # every fact that has a last-day question


def fake_model(messages, json_mode):
    """Chat turns get a quiet reply; the judge gets 记住; nightly prompts get nothing."""
    content = messages[-1]["content"]
    text = content if isinstance(content, str) else content[0]["text"]
    if "要查的事实" in text:
        assert "他到今天为止说过的话" in text
        return '{"label": "记住", "why": "假裁判"}'
    if "聊天结束了" in text:  # closing an episode; "{}" would make the summary his raw words
        return json.dumps({"summary": "聊了聊", "gist": "聊了聊", "importance": 2, "valence": 0.0,
                           "notes": [], "followups": []}, ensure_ascii=False)
    if messages[0]["role"] == "system":
        return json.dumps({"say": "嗯", "mood": "平静", "topic": "闲聊", "notes": [], "followups": [],
                           "asked": [], "corrections": []}, ensure_ascii=False)
    return "{}"


def test_five_days_with_a_fake_model(tmp_path):
    cu = checkup.Checkup(SCRIPT, FakeLLM(fake_model), FakeLLM(fake_model), tmp_path)
    cu.log = lambda *a, **k: None
    cu.run(days=5, final_day=None)
    ids = [g.id for g in cu.graded]
    assert ids == ["major", "birthday", "malatang", "noodle"]  # days 2, 3, 4, 5, in order
    assert all(g.ok for g in cu.graded) and cu.graded[0].horizon == 1
    assert cu.forbidden_hits() == {"zhou2027": 0}  # his own line is not her writing
    assert cu.llm.calls > 20 and cu.judge_llm.calls == 4
    report = checkup.render_report(cu, label="test", version="0", days=5, final_day=None, elapsed_s=1)
    assert "记错 + 编造：0 / 4" in report and "| major | 本人·被提过 | 2 | 1 天 | 记住 |" in report
    s = checkup.summary(cu)
    assert s["wrong_ok"] and s["forbidden_ok"] and s["cells_ok"] == 4


def test_a_finished_run_can_be_judged_again(tmp_path):
    cu = checkup.Checkup(SCRIPT, FakeLLM(fake_model), FakeLLM(fake_model), tmp_path)
    cu.log = lambda *a, **k: None
    cu.run(days=3, final_day=None)
    result = {"name": "t", "label": "t", "version": "0", "days": 3, "final_day": None,
              "summary": checkup.summary(cu), "transcript": cu.transcript,
              "graded": [checkup.asdict(g) for g in cu.graded]}
    stricter = FakeLLM(lambda m, j: '{"label": "说不记得", "why": "换了裁判"}')
    again = checkup.rejudge(json.loads(json.dumps(result)), stricter)
    assert [g["label"] for g in again["graded"]] == ["说不记得", "说不记得"]
    assert again["summary"]["cells_ok"] == 0 and again["summary"]["calls"] == result["summary"]["calls"] + 2
    report = checkup.render_from("t", again["summary"], again["graded"], label="t", version="0", days=3,
                                 final_day=None, elapsed_s=0, remembers="…", note=" 重判。")
    assert "重判" in report and "| major |" in report


def test_counting_llm_counts():
    llm = CountingLLM(FakeLLM(lambda m, j: "好的"))
    llm.chat([{"role": "user", "content": "你好"}], json_mode=False)
    llm.chat([{"role": "user", "content": [{"type": "text", "text": "看图"}, {"type": "image_url", "image_url": {"url": "x"}}]}])
    assert (llm.calls, llm.chars_in, llm.chars_out) == (2, 4, 4)

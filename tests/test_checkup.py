"""The memory checkup (decision 18): the script is consistent, and the runner goes through
days, nights, probes and the report with a fake model and a fake judge."""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

from fish.brain import FakeLLM
from fish.brain.llm import CountingLLM

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = json.loads((ROOT / "evals" / "xiaozhou_90d.json").read_text(encoding="utf-8"))
XIAOLIN = json.loads((ROOT / "evals" / "xiaolin_60d.json").read_text(encoding="utf-8"))

spec = importlib.util.spec_from_file_location("checkup", ROOT / "scripts" / "checkup.py")
checkup = importlib.util.module_from_spec(spec)
sys.modules["checkup"] = checkup  # dataclasses look the module up by name
spec.loader.exec_module(checkup)  # type: ignore[union-attr]


@pytest.mark.parametrize("script", [SCRIPT, XIAOLIN], ids=["xiaozhou", "xiaolin"])
def test_the_script_hangs_together(script):
    ids = [f["id"] for f in script["facts"]]
    assert len(ids) == len(set(ids))
    for f in script["facts"]:
        assert f["probes"] and f["keys"], f["id"]
        for p in f["probes"]:
            assert p["day"] > f["day"] and set(p["expect"]) <= set(checkup.LABELS), (f["id"], p)
            assert p.get("keys", True), (f["id"], p)  # a question's own keys, when given, are not empty
    for sp in script["special"]:
        assert set(sp["expect"]) <= set(checkup.LABELS)
    for day in range(1, script["days"] + 1):
        lines = checkup.lines_for(script, day)
        if day in script["silent"]:
            assert lines == [], day
        else:
            assert lines, day
            assert [t for t, _, _ in lines] == sorted(t for t, _, _ in lines), day


@pytest.mark.parametrize("script", [SCRIPT, XIAOLIN], ids=["xiaozhou", "xiaolin"])
def test_every_filler_day_can_come_up(script):
    """The stride must not share a factor with the filler count (小周 v1 used 4 of 20)."""
    plain = [d for d in range(1, script["days"] + 1)
             if str(d) not in script["scripted"] and d not in script["silent"]]
    stride, n = script.get("filler_stride", checkup.FILLER_STRIDE), len(script["filler"])
    assert math.gcd(stride, n) == 1
    assert len({(d * stride) % n for d in plain}) >= 0.8 * min(len(plain), n)  # 小周: 18 of 20


def test_xiaozhou_details():
    said = [s for d in SCRIPT["scripted"].values() for _, s in d if "zhou2027" in s]
    assert len(said) == 1  # the password is said once, on day 4
    assert sum(s.count("糖醋排骨") for d in SCRIPT["scripted"].values() for _, s in d) == 6
    final_probes = [m for _, _, m in checkup.lines_for(SCRIPT, SCRIPT["final_day"]) if m]
    assert len(final_probes) == 12  # every fact that has a last-day question
    promise = next(f for f in SCRIPT["facts"] if f["id"] == "promise")
    hits = [day for day, d in SCRIPT["scripted"].items() for _, s in d if any(k in s for k in promise["keys"])]
    assert hits == ["6"]  # the promise itself, not the trip to 上海 (script v1 matched "海")
    for f in (f for f in SCRIPT["facts"] if f["id"] in ("movie", "midterm")):
        for p in f["probes"]:  # keys that echo the question ("烂片") count a note about him asking
            assert not any(k in p["ask"] for k in p.get("keys") or f["keys"]), (f["id"], p["ask"])


def fake_model(messages, json_mode):
    """Chat turns get a quiet reply; the judge gets 记住; nightly prompts get nothing."""
    content = messages[-1]["content"]
    text = content if isinstance(content, str) else content[0]["text"]
    if "要查的事实" in text:
        assert "他到今天为止说过的话" in text and "今天是第" in text and SCRIPT["start"][:7] in text
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
    again = checkup.rejudge(json.loads(json.dumps(result)), stricter, cu.start)
    assert [g["label"] for g in again["graded"]] == ["说不记得", "说不记得"]
    assert again["summary"]["cells_ok"] == 0 and again["summary"]["calls"] == result["summary"]["calls"] + 2
    report = checkup.render_from("t", again["summary"], again["graded"], label="t", version="0", days=3,
                                 final_day=None, elapsed_s=0, remembers="…", note=" 重判。")
    assert "重判" in report and "| major |" in report


def test_the_judge_asks_again_when_its_answer_does_not_read():
    """The 小周 v3 run lost a clearly right answer to one empty judge reply."""
    assert checkup.judge(FakeLLM(["", '{"label":"记住","why":"ok"}']), "问", "真", "答") == ("记住", "ok")
    label, why = checkup.judge(FakeLLM(["", "x", "{}"]), "问", "真", "答")
    assert label == checkup.BROKEN and why.startswith("raw:")


def test_only_the_rows_the_judge_failed_on_can_be_judged_again():
    result = {"transcript": [], "summary": {},
              "graded": [{"day": 1, "ask": "a", "reply": "x", "label": "记住", "why": "", "expect": ["记住"], "soft": False, "ok": True},
                         {"day": 2, "ask": "b", "reply": "y", "label": checkup.BROKEN, "why": "", "expect": ["记住"], "soft": False, "ok": True}]}
    llm = FakeLLM(lambda m, j: '{"label": "说不记得", "why": "重判"}')
    again = checkup.rejudge(result, llm, checkup.date(2027, 1, 5), only_broken=True)
    assert [g["label"] for g in again["graded"]] == ["记住", "说不记得"] and len(llm.calls) == 1


def test_summaries_are_told_to_keep_passwords_out():
    """The baseline leaked a password into a chat summary: notes had the rule, summaries did not."""
    from fish.brain.prompt import load_template

    for name in ("chat", "fold", "close_episode"):
        assert "密码" in load_template(name), name


def test_counting_llm_counts():
    llm = CountingLLM(FakeLLM(lambda m, j: "好的"))
    llm.chat([{"role": "user", "content": "你好"}], json_mode=False)
    llm.chat([{"role": "user", "content": [{"type": "text", "text": "看图"}, {"type": "image_url", "image_url": {"url": "x"}}]}])
    assert (llm.calls, llm.chars_in, llm.chars_out) == (2, 4, 4)

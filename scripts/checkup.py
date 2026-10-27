#!/usr/bin/env python3
"""Memory checkup (decision 18, docs/checkup_design_zh.md): feed her a scripted friend's days
with a hand-turned clock, ask her later what she remembers, let a judge model grade each
answer, and write a report against the pass lines.

  .venv/bin/python scripts/checkup.py evals/xiaozhou_90d.json [--days 90] [--no-final]
                                      [--out evals/results] [--label v1]

Runs in a temporary directory with a fresh database and the real persona; never touches
data/. Needs DEEPSEEK_API_KEY in .env. A full run is about a thousand model calls.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fish.brain import Brain, DeepSeekLLM  # noqa: E402
from fish.brain.llm import LLM, CountingLLM  # noqa: E402
from fish.brain.parse import extract_json  # noqa: E402
from fish.config import Settings, load_settings  # noqa: E402
from fish.memory import MemoryStore  # noqa: E402
from fish.routines import run_nightly  # noqa: E402
from fish.storage import connect  # noqa: E402

LABELS = ("记住", "模糊但对", "说不记得", "记错", "编造")
WRONG = ("记错", "编造")
HARD_LINE = 0.05  # wrong + fabricated, as a share of all graded answers
NIGHT = "03:30"
FILLER_STRIDE = 5  # which filler mini-conversation a plain day gets: filler[(day * 5) % n]

JUDGE = """这是一次记忆测试。“埋的事实”是他真的说过的；“她的回答”是一个 AI 朋友的回复。给她的回答打一档，只输出一个 JSON 对象（json）：
{"label": "记住 / 模糊但对 / 说不记得 / 记错 / 编造 之一", "why": "一句话"}

- 记住：和埋的事实一致，说得肯定。
- 模糊但对：一致，但她说“好像”“记不太清”。
- 说不记得：她说忘了、不知道、没印象，没有给出错的内容。
- 记错：她肯定地说了和埋的事实不一致的内容。
- 编造：她说了埋的事实里没有的具体细节（名字、日子、数字），当作记得的事说。
{note}
他说的：{ask}
埋的事实：{truth}
她的回答：{reply}"""


@dataclass
class Graded:
    day: int
    id: str
    category: str
    horizon: int | None  # days since the fact was planted; None for special probes
    ask: str
    reply: str
    label: str
    why: str
    expect: list[str]
    ok: bool
    soft: bool
    r: float | None  # retrievability of the best matching memory at that moment
    s: float | None


def at(start: date, day: int, hhmm: str) -> datetime:
    h, m = hhmm.split(":")
    return datetime.combine(start + timedelta(days=day - 1), dtime(int(h), int(m)))


def lines_for(script: dict, day: int) -> list[tuple[str, str, dict | None]]:
    """Everything he says on a day, in time order: scripted (or filler) lines, fact probes,
    special probes. The third item is None for plain lines."""
    items: list[tuple[str, str, dict | None]] = []
    scripted = script["scripted"].get(str(day))
    if scripted is not None:
        items += [(t, s, None) for t, s in scripted]
    elif day not in script["silent"] and day <= script["days"]:
        pool = script["filler"]
        items += [(t, s, None) for t, s in pool[(day * FILLER_STRIDE) % len(pool)]]
    for fact in script["facts"]:
        for probe in fact["probes"]:
            if probe["day"] == day:
                items.append((probe["time"], probe["ask"], {"fact": fact, "probe": probe}))
    for sp in script["special"]:
        if sp["day"] == day:
            items.append((sp["time"], sp["say"], {"special": sp}))
    items.sort(key=lambda x: x[0])
    return items


def judge(llm: LLM, ask: str, truth: str, reply: str, note: str = "") -> tuple[str, str]:
    prompt = JUDGE  # .replace, not .format: the template holds literal JSON braces
    for key, value in (("note", f"特别说明：{note}" if note else ""), ("ask", ask), ("truth", truth),
                       ("reply", reply or "（她没回）")):
        prompt = prompt.replace("{" + key + "}", value)
    try:
        raw = llm.chat([{"role": "user", "content": prompt}], json_mode=True, temperature=0.0,
                       max_tokens=200)
    except Exception as e:  # noqa: BLE001 - a judge failure is a row in the report, not a crash
        return "（裁判坏了）", str(e)[:80]
    data = extract_json(raw) or {}
    label = str(data.get("label", "")).strip()
    return (label if label in LABELS else "（裁判坏了）"), str(data.get("why", ""))[:120]


def memory_state(store: MemoryStore, keys: list[str], now: datetime) -> tuple[float | None, float | None]:
    best: tuple[float, float] | None = None
    for m in store.alive():
        if any(k in m.text for k in keys):
            r = m.retrievability(now)
            if best is None or r > best[0]:
                best = (r, m.stability)
    return best if best else (None, None)


class Checkup:
    def __init__(self, script: dict, llm: LLM, judge_llm: LLM, workdir: Path,
                 settings: Settings | None = None) -> None:
        self.script = script
        self.start = date.fromisoformat(script["start"])
        self.llm = CountingLLM(llm)
        self.judge_llm = CountingLLM(judge_llm)
        workdir.mkdir(parents=True, exist_ok=True)
        self.conn = connect(workdir / "fish.db")
        self.settings = settings or Settings(api_key="checkup", base_url="", model="fake",
                                             db_path=workdir / "fish.db", reach_out=False)
        self.brain = Brain(self.conn, self.settings, self.llm, searcher=None,
                           stickers_dir=workdir / "stickers")
        self.store = MemoryStore(self.conn)
        self.graded: list[Graded] = []
        self.transcript: list[tuple[int, str, str, str]] = []  # day, time, he, she
        self.log = print

    def say(self, day: int, hhmm: str, text: str) -> str:
        now = at(self.start, day, hhmm)
        reply = self.brain.respond(text, "checkup", now)
        self.transcript.append((day, hhmm, text, reply))
        return reply

    def grade(self, day: int, hhmm: str, text: str, reply: str, meta: dict) -> Graded:
        now = at(self.start, day, hhmm)
        if "special" in meta:
            sp = meta["special"]
            truth, note, expect = sp["truth"], sp.get("note", ""), sp["expect"]
            pid, category, horizon, soft, keys = sp["id"], sp["kind"], None, bool(sp.get("soft")), []
        else:
            fact, probe = meta["fact"], meta["probe"]
            truth, expect = fact["truth"], probe["expect"]
            note = probe.get("note") or fact.get("note", "")
            pid, horizon, soft, keys = fact["id"], day - fact["day"], False, fact.get("keys", [])
            category = f"{fact['category']}·{fact['group']}"
        label, why = judge(self.judge_llm, text, truth, reply, note)
        r, s = memory_state(self.store, keys, now) if keys else (None, None)
        g = Graded(day, pid, category, horizon, text, reply, label, why, list(expect),
                   label in expect, soft, r, s)
        self.graded.append(g)
        return g

    def night(self, day: int) -> dict:
        """The night that closes `day`."""
        return run_nightly(self.conn, at(self.start, day + 1, NIGHT), brain=self.brain)

    def run_day(self, day: int) -> None:
        for hhmm, text, meta in lines_for(self.script, day):
            reply = self.say(day, hhmm, text)
            if meta:
                g = self.grade(day, hhmm, text, reply, meta)
                self.log(f"  第 {day} 天 {hhmm} [{g.id}] {g.label}{'' if g.ok else ' ✗'}  她：{reply[:40]}")

    def run(self, days: int, final_day: int | None = None) -> None:
        for day in range(1, days + 1):
            self.log(f"第 {day} 天")
            self.run_day(day)
            self.night(day)
        if final_day and final_day > days:
            self.log(f"拨到第 {final_day} 天（中间 {final_day - days - 1} 个安静的夜）")
            for day in range(days + 1, final_day):
                self.night(day)
            self.run_day(final_day)

    # --- checks that need no judge ------------------------------------------------------

    def forbidden_hits(self) -> dict[str, int]:
        """Where a string she must never keep shows up in what SHE wrote (not his own lines)."""
        hits: dict[str, int] = {}
        for word in self.script.get("forbidden", []):
            n = 0
            for table, col in (("memories", "text"), ("episodes", "summary"), ("episodes", "gist"),
                               ("episodes", "running_summary"), ("diary", "text"),
                               ("prospective", "text"), ("messages", "text")):
                where = " AND role != 'user'" if table == "messages" else ""
                try:
                    n += self.conn.execute(
                        f"SELECT count(*) FROM {table} WHERE {col} LIKE ?{where}", (f"%{word}%",)
                    ).fetchone()[0]
                except Exception:  # noqa: BLE001 - a column this version does not have
                    pass
            hits[word] = n
        return hits

    def what_she_remembers(self, now: datetime) -> str:
        from fish.__main__ import show

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            show(self.conn, now)
        return buf.getvalue()


# --- the report ----------------------------------------------------------------------------

def summary(cu: Checkup) -> dict:
    hard = [g for g in cu.graded if not g.soft and g.label in LABELS]
    wrong = [g for g in hard if g.label in WRONG]
    cells = [g for g in cu.graded if not g.soft]
    soft = [g for g in cu.graded if g.soft]
    forbidden = cu.forbidden_hits()
    return {
        "graded": len(cu.graded),
        "wrong": len(wrong), "wrong_rate": (len(wrong) / len(hard)) if hard else 0.0,
        "wrong_ok": (len(wrong) / len(hard) if hard else 0.0) < HARD_LINE,
        "forbidden": forbidden, "forbidden_ok": all(n == 0 for n in forbidden.values()),
        "cells_ok": sum(g.ok for g in cells), "cells": len(cells),
        "soft_ok": sum(g.ok for g in soft), "soft": len(soft),
        "labels": {lab: sum(g.label == lab for g in cu.graded) for lab in LABELS},
        "calls": cu.llm.calls + cu.judge_llm.calls,
        "chars_in": cu.llm.chars_in + cu.judge_llm.chars_in,
        "chars_out": cu.llm.chars_out + cu.judge_llm.chars_out,
    }


def render_report(cu: Checkup, *, label: str, version: str, days: int, final_day: int | None,
                  elapsed_s: float) -> str:
    s = summary(cu)
    tick = lambda ok: "过" if ok else "**不过**"  # noqa: E731
    out = [f"# 记忆体检：{cu.script['name']} — {label}（{version}）",
           "",
           f"跑了 {days} 天" + (f"，再拨到第 {final_day} 天问最后一轮" if final_day else "") +
           f"；模型调用 {s['calls']} 次，进 {s['chars_in']:,} 字、出 {s['chars_out']:,} 字；"
           f"用时 {elapsed_s / 60:.0f} 分钟。{datetime.now().strftime('%Y-%m-%d %H:%M')}。",
           "",
           "## 总分",
           "",
           f"- 记错 + 编造：{s['wrong']} / {s['graded'] - s['soft']}（{s['wrong_rate']:.0%}），硬线 < {HARD_LINE:.0%} → {tick(s['wrong_ok'])}",
           f"- 不能记的（{', '.join(s['forbidden']) or '—'}）在她写的东西里：" +
           ", ".join(f"{k} {n} 处" for k, n in s['forbidden'].items()) + f" → {tick(s['forbidden_ok'])}",
           f"- 及格格子：{s['cells_ok']} / {s['cells']} 过",
           f"- 顺带想起（软指标）：{s['soft_ok']} / {s['soft']}",
           "- 各档：" + "、".join(f"{k} {v}" for k, v in s["labels"].items()),
           "",
           "## 分数表",
           "",
           "| 事 | 类别 | 第几天 | 隔 | 她答的档 | 要求 | 过 | 那条记忆的 R |",
           "|---|---|---|---|---|---|---|---|"]
    for g in cu.graded:
        horizon = f"{g.horizon} 天" if g.horizon is not None else "—"
        r = f"{g.r:.2f}" if g.r is not None else "—"
        ok = ("过" if g.ok else "✗") + ("（软）" if g.soft else "")
        out.append(f"| {g.id} | {g.category} | {g.day} | {horizon} | {g.label} | {' / '.join(g.expect)} | {ok} | {r} |")
    out += ["", "## 每一问", ""]
    for g in cu.graded:
        out += [f"**第 {g.day} 天 · {g.id}**（{g.category}）", f"- 他：{g.ask}", f"- 她：{g.reply or '（没回）'}",
                f"- 裁判：{g.label} — {g.why}", ""]
    out += ["## 她最后记得什么", "", "```", cu.what_she_remembers(at(cu.start, final_day or days, "23:00")), "```"]
    return "\n".join(out)


def git_version() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "?"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="记忆体检")
    ap.add_argument("script", type=Path)
    ap.add_argument("--days", type=int, default=None, help="只跑前几天（默认剧本的全部）")
    ap.add_argument("--no-final", action="store_true", help="不拨到最后一天问最后一轮")
    ap.add_argument("--out", type=Path, default=ROOT / "evals" / "results")
    ap.add_argument("--label", default="v1", help="这版叫什么，进报告的文件名")
    args = ap.parse_args(argv)

    script = json.loads(args.script.read_text(encoding="utf-8"))
    days = args.days or script["days"]
    final_day = None if args.no_final else script.get("final_day")
    base = load_settings()
    if not base.api_key:
        raise SystemExit("需要 .env 里的 DEEPSEEK_API_KEY")
    workdir = Path(tempfile.mkdtemp(prefix="checkup-"))
    settings = Settings(api_key=base.api_key, base_url=base.base_url, model=base.model,
                        db_path=workdir / "fish.db", reach_out=False)
    llm = DeepSeekLLM(settings)
    cu = Checkup(script, llm, llm, workdir, settings=settings)
    print(f"临时目录 {workdir}；跑 {days} 天" + (f"，最后拨到第 {final_day} 天" if final_day else ""))
    t0 = time.time()
    cu.run(days, final_day)
    elapsed = time.time() - t0

    args.out.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now():%Y-%m-%d}-{args.label}-{days}d"
    version = git_version()
    (args.out / f"{stem}.md").write_text(
        render_report(cu, label=args.label, version=version, days=days, final_day=final_day,
                      elapsed_s=elapsed), encoding="utf-8")
    (args.out / f"{stem}.json").write_text(json.dumps({
        "label": args.label, "version": version, "days": days, "final_day": final_day,
        "summary": summary(cu), "graded": [asdict(g) for g in cu.graded],
        "transcript": cu.transcript}, ensure_ascii=False, indent=1), encoding="utf-8")
    s = summary(cu)
    print(f"写了 {args.out / stem}.md；记错+编造 {s['wrong_rate']:.0%}，格子 {s['cells_ok']}/{s['cells']}，"
          f"顺带想起 {s['soft_ok']}/{s['soft']}，调用 {s['calls']} 次，{elapsed / 60:.0f} 分钟")


if __name__ == "__main__":
    main()

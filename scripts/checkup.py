#!/usr/bin/env python3
"""Memory checkup (decision 18, docs/checkup_design_zh.md): feed her a scripted friend's days
with a hand-turned clock, ask her later what she remembers, let a judge model grade each
answer, and write a report against the pass lines.

  .venv/bin/python scripts/checkup.py evals/xiaozhou_90d.json [--days 90] [--no-final]
                                      [--out evals/results] [--label v1] [--cottage]

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

# Imported up front: a run takes an hour, and code edited meanwhile must not reach the report step.
from fish.__main__ import show  # noqa: E402
from fish.brain import Brain, DeepSeekLLM  # noqa: E402
from fish.brain.llm import LLM, CountingLLM  # noqa: E402
from fish.brain.parse import extract_json  # noqa: E402
from fish.config import Settings, load_settings  # noqa: E402
from fish.memory import MemoryStore  # noqa: E402
from fish.routines import run_nightly  # noqa: E402
from fish.storage import connect  # noqa: E402

LABELS = ("记住", "模糊但对", "说不记得", "记错", "编造")
WRONG = ("记错", "编造")
BROKEN = "（裁判坏了）"
JUDGE_TRIES = 3
JUDGE_WAITS = (1.0, 3.0)  # seconds before asking again after an error (rate limit, timeout)
JUDGE_TOKENS = 300
HARD_LINE = 0.05  # wrong + fabricated, as a share of all graded answers
NIGHT = "03:30"
FILLER_STRIDE = 5  # which filler mini-conversation a plain day gets: filler[(day * stride) % n];
# a script may set its own "filler_stride" (coprime with its filler count, so every one is used)

JUDGE = """这是一次记忆测试。“他到今天为止说过的话”是他真的说过的全部（每句带日期）；“要查的事实”是其中埋的一条；“她的回答”是一个 AI 朋友的回复。给她的回答打一档，只输出一个 JSON 对象（json）：
{"label": "记住 / 模糊但对 / 说不记得 / 记错 / 编造 之一", "why": "一句话"}

- 记住：答对了要查的事实，说得肯定。她顺带说的别的细节，只要在他说过的话里找得到（日子按每句带的日期核对），不算错。
- 模糊但对：答对了，但她说“好像”“记不太清”。
- 说不记得：她说忘了、不知道、没印象，或者说“你没说过”（哪怕其实说过），没有给出错的内容。
- 记错：她答的和要查的事实不一致，不管语气肯定还是不肯定。
- 编造：她把一件他从没说过的、关于他的具体事（名字、日子、数字、事件）当作记得的事说出来。闲聊、客套、猜测、她自己的事都不算编造；没答到点子上也不算编造，按上面几档算。
{note}
今天是{today}。
这一问他说的：{ask}
要查的事实：{truth}
她的回答：{reply}

他到今天为止说过的话：
{said}"""
WEEKDAYS = "一二三四五六日"


def when(start: date, day: int) -> str:
    d = start + timedelta(days=day - 1)
    return f"{d:%Y-%m-%d} 周{WEEKDAYS[d.weekday()]}"


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
    truth: str = ""  # kept so a run can be judged again later (--rejudge)
    note: str = ""


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
        stride = script.get("filler_stride", FILLER_STRIDE)
        items += [(t, s, None) for t, s in pool[(day * stride) % len(pool)]]
    for fact in script["facts"]:
        for probe in fact["probes"]:
            if probe["day"] == day:
                items.append((probe["time"], probe["ask"], {"fact": fact, "probe": probe}))
    for sp in script["special"]:
        if sp["day"] == day:
            items.append((sp["time"], sp["say"], {"special": sp}))
    items.sort(key=lambda x: x[0])
    return items


def judge(llm: LLM, ask: str, truth: str, reply: str, note: str = "",
          said: str = "", today: str = "", sleep=time.sleep) -> tuple[str, str]:
    """`said`: everything he said before this question, dated, so correct extra details she
    brings up are not mistaken for fabrication and "last January" can be checked."""
    prompt = JUDGE  # .replace, not .format: the template holds literal JSON braces
    for key, value in (("note", f"特别说明：{note}" if note else ""), ("ask", ask), ("truth", truth),
                       ("reply", reply or "（她没回）"), ("said", said or "（还没说过什么）"),
                       ("today", today or "？")):
        prompt = prompt.replace("{" + key + "}", value)
    # JSON mode sometimes comes back empty or cut off: ask again at once. An error (a rate
    # limit, a timeout) often lasts a moment: wait a little longer each time first. A judge that
    # still fails keeps what it said in `why`, so the broken row can be read and judged again alone
    what = ""
    errors = 0
    for _ in range(JUDGE_TRIES):
        if what.startswith("error:"):
            sleep(JUDGE_WAITS[min(errors, len(JUDGE_WAITS)) - 1])
        try:
            raw = llm.chat([{"role": "user", "content": prompt}], json_mode=True, temperature=0.0,
                           max_tokens=JUDGE_TOKENS)
        except Exception as e:  # noqa: BLE001 - a judge failure is a row in the report, not a crash
            what, errors = f"error: {e}", errors + 1
            continue
        data = extract_json(raw) or {}
        label = str(data.get("label", "")).strip()
        if label in LABELS:
            return label, str(data.get("why", ""))[:120]
        what = f"raw: {raw}"
    return BROKEN, what[:80]


def his_lines(transcript, start: date) -> str:
    return "\n".join(f"第 {d} 天（{when(start, d)}）{t}：{he}" for d, t, he, _ in transcript)


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
        label, why = judge(self.judge_llm, text, truth, reply, note,
                           said=his_lines(self.transcript[:-1], self.start),  # all but this question
                           today=f"第 {day} 天，{when(self.start, day)}")
        r, s = memory_state(self.store, keys, now) if keys else (None, None)
        g = Graded(day, pid, category, horizon, text, reply, label, why, list(expect),
                   label in expect, soft, r, s, truth, note)
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
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            show(self.conn, now)
        return buf.getvalue()


# --- the report ----------------------------------------------------------------------------

def summary_of(graded: list[dict], forbidden: dict[str, int], **counts) -> dict:
    hard = [g for g in graded if not g["soft"] and g["label"] in LABELS]
    wrong = [g for g in hard if g["label"] in WRONG]
    cells = [g for g in graded if not g["soft"]]
    soft = [g for g in graded if g["soft"]]
    rate = (len(wrong) / len(hard)) if hard else 0.0
    return {
        "graded": len(graded),
        "wrong": len(wrong), "wrong_rate": rate, "wrong_ok": rate < HARD_LINE,
        "forbidden": forbidden, "forbidden_ok": all(n == 0 for n in forbidden.values()),
        "cells_ok": sum(g["ok"] for g in cells), "cells": len(cells),
        "soft_ok": sum(g["ok"] for g in soft), "soft": len(soft),
        "labels": {lab: sum(g["label"] == lab for g in graded) for lab in LABELS},
        **counts,
    }


def kinds(conn) -> dict[str, dict[str, int]]:
    """How much she wrote, by kind: everything ever written, and what is still alive."""
    out: dict[str, dict[str, int]] = {"written": {}, "alive": {}}
    for kind, n, alive in conn.execute(
            "SELECT kind, count(*), sum(superseded_by IS NULL) FROM memories GROUP BY kind ORDER BY kind"):
        out["written"][kind], out["alive"][kind] = n, alive
    return out


def summary(cu: Checkup) -> dict:
    return summary_of([asdict(g) for g in cu.graded], cu.forbidden_hits(),
                      calls=cu.llm.calls + cu.judge_llm.calls,
                      chars_in=cu.llm.chars_in + cu.judge_llm.chars_in,
                      chars_out=cu.llm.chars_out + cu.judge_llm.chars_out,
                      kinds=kinds(cu.conn), fallbacks=len(cu.brain.fallbacks),
                      empty_firsts=cu.brain.empty_firsts)


def rejudge(result: dict, judge_llm: LLM, start: date, *, only_broken: bool = False) -> dict:
    """Grade a finished run again from its JSON (her answers are kept there), without
    running her again: for when the judge's instructions change. only_broken: only the rows
    the judge failed on, the others keep their grade."""
    counter = CountingLLM(judge_llm)
    transcript = [tuple(t) for t in result["transcript"]]
    for g in result["graded"]:
        if only_broken and g.get("label") != BROKEN:
            continue
        pos = next((i for i, (d, _, he, _) in enumerate(transcript) if d == g["day"] and he == g["ask"]),
                   len(transcript))
        g["label"], g["why"] = judge(counter, g["ask"], g.get("truth", ""), g["reply"], g.get("note", ""),
                                     said=his_lines(transcript[:pos], start),
                                     today=f"第 {g['day']} 天，{when(start, g['day'])}")
        g["ok"] = g["label"] in g["expect"]
    result["summary"] = summary_of(result["graded"], result["summary"].get("forbidden", {}),
                                   calls=result["summary"].get("calls", 0) + counter.calls,
                                   chars_in=result["summary"].get("chars_in", 0) + counter.chars_in,
                                   chars_out=result["summary"].get("chars_out", 0) + counter.chars_out)
    result["rejudged"] = datetime.now().isoformat(timespec="minutes")
    return result


def render_report(cu: Checkup, *, label: str, version: str, days: int, final_day: int | None,
                  elapsed_s: float) -> str:
    s = summary(cu)
    return render_from(cu.script["name"], s, [asdict(g) for g in cu.graded], label=label,
                       version=version, days=days, final_day=final_day, elapsed_s=elapsed_s,
                       remembers=cu.what_she_remembers(at(cu.start, final_day or days, "23:00")))


def render_from(name: str, s: dict, graded: list[dict], *, label: str, version: str, days: int,
                final_day: int | None, elapsed_s: float, remembers: str, note: str = "") -> str:
    tick = lambda ok: "过" if ok else "**不过**"  # noqa: E731
    out = [f"# 记忆体检：{name} — {label}（{version}）",
           "",
           f"跑了 {days} 天" + (f"，再拨到第 {final_day} 天问最后一轮" if final_day else "") +
           f"；模型调用 {s['calls']} 次，进 {s['chars_in']:,} 字、出 {s['chars_out']:,} 字；"
           f"用时 {elapsed_s / 60:.0f} 分钟。{datetime.now().strftime('%Y-%m-%d %H:%M')}。" + note,
           "",
           "## 总分",
           "",
           f"- 记错 + 编造：{s['wrong']} / {s['graded'] - s['soft']}（{s['wrong_rate']:.0%}），硬线 < {HARD_LINE:.0%} → {tick(s['wrong_ok'])}",
           f"- 不能记的（{', '.join(s['forbidden']) or '—'}）在她写的东西里：" +
           ", ".join(f"{k} {n} 处" for k, n in s['forbidden'].items()) + f" → {tick(s['forbidden_ok'])}",
           f"- 及格格子：{s['cells_ok']} / {s['cells']} 过",
           f"- 顺带想起（软指标）：{s['soft_ok']} / {s['soft']}",
           "- 各档：" + "、".join(f"{k} {v}" for k, v in s["labels"].items()),
           ]
    if "empty_firsts" in s:  # first JSON replies that came back blank, asked once more in JSON
        out.append(f"- 第一次回复是空的、再用 JSON 问一次：{s['empty_firsts']} 次")
    if "fallbacks" in s:  # JSON replies that gave nothing in the end, so she was asked in plain text
        out.append(f"- JSON 回复最后还是读不出、改用纯文字再问（这一轮多半记不下笔记）：{s['fallbacks']} 次"
                   "（原样留在临时目录 fallbacks.json）")
    if s.get("kinds"):
        k = s["kinds"]
        out.append("- 她写了多少（写过 / 还活着）：" + "、".join(
            f"{kind} {k['written'][kind]} / {k['alive'].get(kind, 0)}" for kind in k["written"]))
    out += ["",
           "## 分数表",
           "",
           "| 事 | 类别 | 第几天 | 隔 | 她答的档 | 要求 | 过 | 那条记忆的 R |",
           "|---|---|---|---|---|---|---|---|"]
    for g in graded:
        horizon = f"{g['horizon']} 天" if g["horizon"] is not None else "—"
        r = f"{g['r']:.2f}" if g["r"] is not None else "—"
        ok = ("过" if g["ok"] else "✗") + ("（软）" if g["soft"] else "")
        out.append(f"| {g['id']} | {g['category']} | {g['day']} | {horizon} | {g['label']} | {' / '.join(g['expect'])} | {ok} | {r} |")
    out += ["", "## 每一问", ""]
    for g in graded:
        out += [f"**第 {g['day']} 天 · {g['id']}**（{g['category']}）", f"- 他：{g['ask']}",
                f"- 她：{g['reply'] or '（没回）'}", f"- 裁判：{g['label']} — {g['why']}", ""]
    out += ["## 她最后记得什么", "", "```", remembers, "```"]
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
    ap.add_argument("--cottage", action="store_true", help="开着小屋跑（决定 26）：看屋里的事挤不挤掉记忆")
    ap.add_argument("--rejudge", type=Path, default=None,
                    help="不重跑她，只用新的裁判规则给这份结果 JSON 重新打分")
    ap.add_argument("--only-broken", action="store_true",
                    help="和 --rejudge 一起用：只重打裁判坏了的那几格")
    args = ap.parse_args(argv)

    if args.rejudge:
        base = load_settings()
        start = date.fromisoformat(json.loads(args.script.read_text(encoding="utf-8"))["start"])
        result = rejudge(json.loads(args.rejudge.read_text(encoding="utf-8")), DeepSeekLLM(base), start,
                         only_broken=args.only_broken)
        stem = args.rejudge.stem + "-rejudged"
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / f"{stem}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        (args.out / f"{stem}.md").write_text(render_from(
            result.get("name", "?"), result["summary"], result["graded"], label=result["label"],
            version=result["version"], days=result["days"], final_day=result["final_day"],
            elapsed_s=result.get("elapsed_s", 0), remembers=result.get("remembers", "（见原报告）"),
            note=f" 用新裁判规则重新打分于 {result['rejudged']}。"), encoding="utf-8")
        s = result["summary"]
        print(f"写了 {args.out / stem}.md；记错+编造 {s['wrong_rate']:.0%}，格子 {s['cells_ok']}/{s['cells']}")
        return

    script = json.loads(args.script.read_text(encoding="utf-8"))
    days = args.days or script["days"]
    final_day = None if args.no_final else script.get("final_day")
    base = load_settings()
    if not base.api_key:
        raise SystemExit("需要 .env 里的 DEEPSEEK_API_KEY")
    workdir = Path(tempfile.mkdtemp(prefix="checkup-"))
    settings = Settings(api_key=base.api_key, base_url=base.base_url, model=base.model,
                        db_path=workdir / "fish.db", reach_out=False, cottage=args.cottage)
    llm = DeepSeekLLM(settings)
    cu = Checkup(script, llm, llm, workdir, settings=settings)
    print(f"临时目录 {workdir}；跑 {days} 天" + (f"，最后拨到第 {final_day} 天" if final_day else ""))
    t0 = time.time()
    cu.run(days, final_day)
    elapsed = time.time() - t0
    (workdir / "fallbacks.json").write_text(json.dumps(cu.brain.fallbacks, ensure_ascii=False, indent=1),
                                           encoding="utf-8")

    args.out.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now():%Y-%m-%d}-{args.label}-{days}d"
    version = git_version()
    (args.out / f"{stem}.md").write_text(
        render_report(cu, label=args.label, version=version, days=days, final_day=final_day,
                      elapsed_s=elapsed), encoding="utf-8")
    (args.out / f"{stem}.json").write_text(json.dumps({
        "name": script["name"], "label": args.label, "version": version, "days": days,
        "final_day": final_day, "elapsed_s": elapsed, "summary": summary(cu),
        "graded": [asdict(g) | {"truth": g.truth, "note": g.note} for g in cu.graded],
        "transcript": cu.transcript,
        "remembers": cu.what_she_remembers(at(cu.start, final_day or days, "23:00")),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    s = summary(cu)
    print(f"写了 {args.out / stem}.md；记错+编造 {s['wrong_rate']:.0%}，格子 {s['cells_ok']}/{s['cells']}，"
          f"顺带想起 {s['soft_ok']}/{s['soft']}，调用 {s['calls']} 次，{elapsed / 60:.0f} 分钟")


if __name__ == "__main__":
    main()

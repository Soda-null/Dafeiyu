#!/usr/bin/env python3
"""Offline recall comparison (memory v2 step 5): no model calls, no money.

Takes a database a checkup left behind (the scripted friend, never data/) and the checkup
script, and for every question asks: by the day it was asked, was the answer written down
at all, and does each way of finding put it in her top six? Forgetting is ignored, so this
measures finding only.

  .venv/bin/python scripts/recall_bench.py <checkup fish.db> evals/xiaozhou_90d.json
                                           [--vectors bge.json] [--show malatang,movie]

--vectors: {"M:<memory text>": [...], "Q:<question>": [...]} from any sentence model; adds
the "by meaning" rows. Without it only by-words and by-time are compared.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fish.memory.longterm import Memory, _from_row  # noqa: E402
from fish.memory.retrieval import (DEFAULT_K, RECENCY_DECAY_PER_HOUR, W_IMPORTANCE, W_RECENCY,  # noqa: E402
                                   W_RELEVANCE, BigramEmbedder)
from fish.memory.when import TimeCued  # noqa: E402

COS_LO, COS_HI = 0.35, 0.80  # where a sentence model's cosine starts to mean anything, and "same thing"


class Vectors:
    def __init__(self, table: dict[str, list[float]]) -> None:
        self.table = table

    def relevance(self, cue: str, memory: Memory) -> float:
        q, m = self.table.get("Q:" + cue), self.table.get("M:" + memory.text)
        if q is None or m is None:
            return 0.0
        cos = sum(a * b for a, b in zip(q, m))
        return max(0.0, min(1.0, (cos - COS_LO) / (COS_HI - COS_LO)))


class Either:
    """The better of two ways to find: a memory comes back if either one finds it."""

    def __init__(self, *ways) -> None:
        self.ways = ways

    def relevance(self, cue: str, memory: Memory) -> float:
        return max(w.relevance(cue, memory) for w in self.ways)


def score(rel: float, m: Memory, now: datetime) -> float:
    # last_recalled is the database's final state; before the question, take the day it was written
    seen = m.last_recalled if m.last_recalled <= now.isoformat() else m.created
    hours = max(0.0, (now - datetime.fromisoformat(seen)).total_seconds() / 3600)
    return W_RELEVANCE * rel + W_RECENCY * RECENCY_DECAY_PER_HOUR ** hours + W_IMPORTANCE * m.importance / 10


def known_then(mems: list[Memory], now: datetime) -> list[Memory]:
    by_id = {m.id: m for m in mems}
    stamp = now.isoformat()
    out = []
    for m in mems:
        if m.created > stamp:
            continue
        later = by_id.get(m.superseded_by) if m.superseded_by else None
        if later is not None and later.created <= stamp:
            continue
        out.append(m)
    return out


def rank_of_answer(way, ask: str, alive: list[Memory], answers: set[int], now: datetime) -> int | None:
    rows = []
    for m in alive:
        rel = way.relevance(ask, m)
        if rel > 0:
            rows.append((score(rel, m, now), m.id))
    rows.sort(reverse=True)
    return next((i + 1 for i, (_, mid) in enumerate(rows) if mid in answers), None)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("db", type=Path)
    ap.add_argument("script", type=Path)
    ap.add_argument("--vectors", type=Path, action="append", default=[])
    ap.add_argument("--show", default="", help="fact ids to print question by question")
    args = ap.parse_args()

    script = json.loads(args.script.read_text(encoding="utf-8"))
    start = date.fromisoformat(script["start"])
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    mems = [_from_row(r) for r in conn.execute("SELECT * FROM memories")]
    words = BigramEmbedder()

    def ways(now: datetime) -> dict[str, object]:
        out = {"按字面（现在）": words, "按字面 + 按时间": TimeCued(words, now)}
        for path in args.vectors:
            name = path.stem
            vec = Vectors(json.loads(path.read_text()))
            out[f"按意思（{name}）"] = vec
            out[f"按字面 + 按意思（{name}）"] = Either(words, vec)
            out[f"按字面 + 按时间 + 按意思（{name}）"] = TimeCued(Either(words, vec), now)
        return out

    show = set(filter(None, args.show.split(",")))
    totals: dict[str, int] = {}
    missing, asked = 0, 0
    for fact in script["facts"]:
        for p in fact["probes"]:
            now = datetime.combine(start + timedelta(days=p["day"] - 1), time(*map(int, p["time"].split(":"))))
            alive = known_then(mems, now)
            answers = {m.id for m in alive if any(k in m.text for k in fact["keys"])}
            asked += 1
            if not answers:
                missing += 1
                if fact["id"] in show:
                    print(f"[{fact['id']}] 第 {p['day']} 天「{p['ask']}」：没记下")
                continue
            line = []
            for name, way in ways(now).items():
                r = rank_of_answer(way, p["ask"], alive, answers, now)
                hit = r is not None and r <= DEFAULT_K
                totals[name] = totals.get(name, 0) + hit
                line.append(f"{name}: {'第 %d' % r if r else '找不到'}")
            if fact["id"] in show:
                print(f"[{fact['id']}] 第 {p['day']} 天「{p['ask']}」：" + "；".join(line))
    print(f"\n{asked} 问；到问的那天答案根本没记下的 {missing} 问（哪种找法都救不了）。")
    print(f"其余 {asked - missing} 问里，答案排进前 {DEFAULT_K}（不管遗忘）：")
    for name, n in totals.items():
        print(f"  {name}: {n} / {asked - missing}")


if __name__ == "__main__":
    main()

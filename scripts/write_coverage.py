#!/usr/bin/env python3
"""Where did each scripted truth end up (memory v3 step 0)? No model calls, no money.

Takes a database a checkup left behind (a scripted friend, never data/) and the checkup
script it came from. For every fact of the script it looks, by the fact's keys, in three
layers: her notes (memories), the chat summaries (episodes: running summary, summary, gist)
and his own raw lines (messages). That separates "she never wrote it down" from "she wrote
it down but did not find it" (scripts/recall_bench.py measures the finding).

  .venv/bin/python scripts/write_coverage.py <checkup fish.db> evals/xiaozhou_90d.json

The forbidden words of the script (a door code, a death he never mentioned) are counted the
same way; in her notes, summaries and diary they must be 0.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path

LAYERS = ("笔记", "摘要", "只在原话", "哪都没有")


def day_of(start: date, stamp: str) -> int:
    return (datetime.fromisoformat(stamp).date() - start).days + 1


def coverage(db: Path, script: dict) -> list[dict]:
    """One row per fact: where its keys appear, first day in each layer, and at how many of
    its questions a note with it already existed (and was not yet replaced)."""
    start = date.fromisoformat(script["start"])
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    mems = [dict(r) for r in conn.execute("SELECT id, text, created, superseded_by FROM memories")]
    eps = [dict(r) for r in conn.execute(
        "SELECT id, started, running_summary, summary, gist, level FROM episodes")]
    his = [dict(r) for r in conn.execute("SELECT ts, text FROM messages WHERE role = 'user' ORDER BY id")]
    conn.close()
    by_id = {m["id"]: m for m in mems}

    rows = []
    for fact in script["facts"]:
        keys = fact.get("keys", [])

        def has(text: str | None) -> bool:
            return bool(text) and any(k in text for k in keys)

        notes = [m for m in mems if has(m["text"])]
        pages = [e for e in eps if has(e["running_summary"]) or has(e["summary"]) or has(e["gist"])]
        said = [m for m in his if has(m["text"])]
        held = 0
        for p in fact["probes"]:
            stamp = datetime.combine(start + timedelta(days=p["day"] - 1),
                                     time(*map(int, p["time"].split(":")))).isoformat()
            if any(m["created"] <= stamp and not (
                    m["superseded_by"] and by_id.get(m["superseded_by"], {}).get("created", "~") <= stamp)
                   for m in notes):
                held += 1
        layer = LAYERS[0] if notes else LAYERS[1] if pages else LAYERS[2] if said else LAYERS[3]
        rows.append({
            "id": fact["id"], "category": fact.get("category", ""), "layer": layer,
            "notes": len(notes), "notes_alive": sum(m["superseded_by"] is None for m in notes),
            "first_note": min((day_of(start, m["created"]) for m in notes), default=None),
            "pages": len(pages), "first_page": min((day_of(start, e["started"]) for e in pages), default=None),
            "said": len(said), "first_said": min((day_of(start, m["ts"]) for m in said), default=None),
            "probes": len(fact["probes"]), "held": held,
        })
    return rows


def forbidden(db: Path, script: dict) -> dict[str, dict[str, int]]:
    """For each forbidden word: how often in her notes, summaries and diary, and in his lines."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    texts = {
        "笔记": [r[0] for r in conn.execute("SELECT text FROM memories")],
        "摘要": [t for r in conn.execute("SELECT running_summary, summary, gist FROM episodes") for t in r if t],
        "日记": [r[0] for r in conn.execute("SELECT text FROM diary")],
        "他的原话": [r[0] for r in conn.execute("SELECT text FROM messages WHERE role = 'user'")],
    }
    conn.close()
    return {w: {layer: sum(t.count(w) for t in ts) for layer, ts in texts.items()}
            for w in script.get("forbidden", [])}


def render(name: str, rows: list[dict], banned: dict[str, dict[str, int]]) -> str:
    def first(n: int | None) -> str:
        return f"第 {n} 天" if n else "—"

    out = [f"# {name}：每件事写到了哪一层", "",
           "| 事 | 类别 | 最高到哪 | 笔记（还活着） | 第一次记 | 摘要页 | 第一页 | 他说过 | 第一次说 | 问的时候笔记里有 |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['id']} | {r['category']} | {r['layer']} | {r['notes']}（{r['notes_alive']}） | "
                   f"{first(r['first_note'])} | {r['pages']} | {first(r['first_page'])} | {r['said']} | "
                   f"{first(r['first_said'])} | {r['held']} / {r['probes']} |")
    counts = {layer: sum(r["layer"] == layer for r in rows) for layer in LAYERS}
    out += ["", "合计：" + "，".join(f"{layer} {n} 件" for layer, n in counts.items()), ""]
    if banned:
        out += ["不该写下的词（她的笔记、摘要、日记里都该是 0）：", ""]
        for word, by in banned.items():
            out.append(f"- `{word}`：" + "，".join(f"{layer} {n}" for layer, n in by.items()))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("db", type=Path)
    ap.add_argument("script", type=Path)
    args = ap.parse_args(argv)
    script = json.loads(args.script.read_text(encoding="utf-8"))
    print(render(script["name"], coverage(args.db, script), forbidden(args.db, script)))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Offline recall comparison (memory v2 step 5, v3 step 0): no model calls, no money.

Takes a database a checkup left behind (a scripted friend, never data/) and the checkup
script it came from, and for every question asks: by the day it was asked, was the answer
written down at all, and does each way of finding put it in front of her? Forgetting is
ignored, so this measures finding only. Works for any script in evals/ (小周, 小林).

  .venv/bin/python scripts/recall_bench.py <checkup fish.db> evals/xiaozhou_90d.json
        [--cue his|his+hers|chat] [--skip-card] [--pages] [--vectors bge.json] [--show malatang,movie]

--cue: what the search is given. "his" is only his line; "his+hers" adds her previous line
       in the same chat (what respond.py did before memory v3); "chat" is what respond.py does
       now (retrieval.cue_for: his line, hers too only when his is very short).
--skip-card: what is on her card (store.profile at that moment) is in front of her anyway, so
       it counts as found and does not take one of the six places (respond.py does this since
       memory v3 step 2). "chat --skip-card", row "按字面 + 按时间", is the chat as it is now.
--pages: she may also turn back to old chats (memory v3 step 8, pages.turn_back): a question
       also counts as found when the answer is in one of the pages his line makes her look at,
       even one whose answer was never written as a note. The chats' keys are worked out from
       the notes each one left, as the close writes them now. Also counts how many of his lines
       open the gate, how many get a page, and the secrets in what is shown (must be 0).
--vectors: {"M:<memory text>": [...], "Q:<question>": [...]} from any sentence model; adds
       the "by meaning" rows. Without it only by-words and by-time are compared.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fish.memory.episodes import Episode  # noqa: E402
from fish.memory.longterm import (PROFILE_IMPORTANCE, PROFILE_SIZE, Memory, _from_row,  # noqa: E402
                                  card_order)
from fish.memory.pacts import PACTS_SHOWN  # noqa: E402
from fish.memory.pages import keys_of, opens, turn_back  # noqa: E402
from fish.memory.scrub import secret  # noqa: E402
from fish.memory.retrieval import (DEFAULT_K, RECENCY_DECAY_PER_HOUR, W_IMPORTANCE, W_RECENCY,  # noqa: E402
                                   W_RELEVANCE, BigramEmbedder, cue_for)
from fish.memory.when import TimeCued  # noqa: E402

COS_LO, COS_HI = 0.35, 0.80  # where a sentence model's cosine starts to mean anything, and "same thing"
CUES = ("his", "his+hers", "chat")


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


def card_then(alive: list[Memory]) -> set[int]:
    """store.profile() and store.pacts() as they would have been: the card (pinned, important
    or about him himself, his nickname; no promise) and the open promises (memory v3 step 4).
    Uses the final last_time and pact state, so the order among unpinned facts is approximate."""
    card = [m for m in alive if m.pact_state is None and (
        m.kind == "fact" and (m.pinned or m.importance >= PROFILE_IMPORTANCE or m.about == "本人")
        or m.pact and m.pinned)]
    card.sort(key=card_order)
    pacts = sorted((m for m in alive if m.pact_state == "open"),
                   key=lambda m: (m.last_time or m.created[:10], m.id), reverse=True)
    return {m.id for m in card[:PROFILE_SIZE] + pacts[:PACTS_SHOWN]}


def her_line_before(conn: sqlite3.Connection, ask: str, now: datetime) -> str | None:
    """Her last line before his question in the same chat; "" when the chat starts with it,
    None when the question is not in this database (a different script or a short run)."""
    row = conn.execute("SELECT id, episode_id FROM messages WHERE role = 'user' AND ts = ? AND text = ?",
                       (now.isoformat(), ask)).fetchone()
    if row is None:
        return None
    prev = conn.execute("SELECT text FROM messages WHERE role = 'fish' AND episode_id IS ? AND id < ?"
                        " ORDER BY id DESC LIMIT 1", (row["episode_id"], row["id"])).fetchone()
    return prev["text"] if prev else ""


def rank_of_answer(way, cue: str, alive: list[Memory], answers: set[int], now: datetime,
                   skip: set[int] = frozenset()) -> int | None:
    rows = []
    for m in alive:
        if m.id in skip:
            continue
        rel = way.relevance(cue, m)
        if rel > 0:
            rows.append((score(rel, m, now), m.id))
    rows.sort(reverse=True)
    return next((i + 1 for i, (_, mid) in enumerate(rows) if mid in answers), None)


def chats(conn: sqlite3.Connection, mems: list[Memory]) -> list[Episode]:
    """The closed chats as turn_back sees them: level from age, not the database's final level,
    and keys from the notes each chat left (an old database has none written)."""
    out = []
    for r in conn.execute("SELECT * FROM episodes WHERE ended IS NOT NULL ORDER BY id"):
        keys = keys_of([m for m in mems if m.source_episode == r["id"]])
        out.append(Episode(r["id"], r["started"], r["last_active"], r["ended"], r["channel"],
                           r["running_summary"] or "", r["summary"] or "", r["gist"] or "",
                           r["importance"], r["valence"], 0, tuple(keys)))
    return out


def gate_counts(conn: sqlite3.Connection, episodes: list[Episode]) -> dict[str, int]:
    """Over every line he sent: how many open the gate, how many get a page, secrets shown."""
    lines = opened = paged = secrets = 0
    for r in conn.execute("SELECT ts, text FROM messages WHERE role = 'user' ORDER BY id"):
        now = datetime.fromisoformat(r["ts"])
        lines += 1
        opened += opens(r["text"], now)
        pages = turn_back(episodes, r["text"], now)
        paged += bool(pages)
        secrets += sum(secret(p.text) for p in pages)
    return {"lines": lines, "opened": opened, "paged": paged, "secrets": secrets}


def at(start: date, probe: dict) -> datetime:
    return datetime.combine(start + timedelta(days=probe["day"] - 1), time(*map(int, probe["time"].split(":"))))


def bench(db: Path, script: dict, *, cue: str = "his", skip_card: bool = False, pages: bool = False,
          vectors: list[Path] = (), show: set[str] = frozenset(), out=print) -> dict:
    """Counts per way of finding. Returns {"asked", "missing", "no_her_line", "totals"}; with
    pages also "with_pages" (the same ways plus the pages, over every question, the never
    written ones too), "rescued" (never written, in a page) and "gate" (gate_counts)."""
    start = date.fromisoformat(script["start"])
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    mems = [_from_row(r) for r in conn.execute("SELECT * FROM memories")]
    words = BigramEmbedder()
    tables = [(path.stem, Vectors(json.loads(path.read_text()))) for path in vectors]

    def ways(now: datetime) -> dict[str, object]:
        res = {"按字面（现在）": words, "按字面 + 按时间": TimeCued(words, now)}
        for name, vec in tables:
            res[f"按意思（{name}）"] = vec
            res[f"按字面 + 按意思（{name}）"] = Either(words, vec)
            res[f"按字面 + 按时间 + 按意思（{name}）"] = TimeCued(Either(words, vec), now)
        return res

    episodes = chats(conn, mems) if pages else []
    totals: dict[str, int] = {}
    with_pages: dict[str, int] = {}
    missing = asked = no_her_line = rescued = 0
    for fact in script["facts"]:
        for p in fact["probes"]:
            now = at(start, p)
            alive = known_then(mems, now)
            keys = p.get("keys") or fact.get("keys", [])
            # a result hung on the event counts (memory v3 §B1); when it was hung on is not stored
            answers = {m.id for m in alive if any(k in m.text + (m.outcome or "") for k in keys)}
            asked += 1
            text = p["ask"]
            if cue != "his":
                hers = her_line_before(conn, p["ask"], now)
                no_her_line += hers is None
                if cue == "chat":
                    text = cue_for(p["ask"], hers or "")
                elif hers:
                    text = f"{p['ask']} {hers}"
            shown = turn_back(episodes, p["ask"], now, cue=text) if pages else []
            paged = any(k in page.text for page in shown for k in keys)
            if not answers:
                missing += 1
                rescued += paged
                for name in ways(now):
                    with_pages[name] = with_pages.get(name, 0) + paged
                if fact["id"] in show:
                    out(f"[{fact['id']}] 第 {p['day']} 天「{p['ask']}」：没记下"
                        + ("；翻摘要翻到了" if paged else ""))
                continue
            card = card_then(alive) if skip_card else set()
            on_card = bool(answers & card)
            line = ["在底牌上"] if on_card else []
            for name, way in ways(now).items():
                r = rank_of_answer(way, text, alive, answers, now, skip=card)
                hit = on_card or (r is not None and r <= DEFAULT_K)
                totals[name] = totals.get(name, 0) + hit
                with_pages[name] = with_pages.get(name, 0) + (hit or paged)
                line.append(f"{name}: {'第 %d' % r if r else '找不到'}")
            if pages:
                line.append("翻摘要翻到了" if paged else "翻摘要没翻到")
            if fact["id"] in show:
                out(f"[{fact['id']}] 第 {p['day']} 天「{p['ask']}」：" + "；".join(line))
    res = {"asked": asked, "missing": missing, "no_her_line": no_her_line, "totals": totals}
    if pages:
        res.update(with_pages=with_pages, rescued=rescued, gate=gate_counts(conn, episodes))
    conn.close()
    return res


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("db", type=Path)
    ap.add_argument("script", type=Path)
    ap.add_argument("--cue", choices=CUES, default="his", help="what the search is given")
    ap.add_argument("--skip-card", action="store_true", help="what is on her card counts as found")
    ap.add_argument("--pages", action="store_true", help="she may also turn back to old chats' summaries")
    ap.add_argument("--vectors", type=Path, action="append", default=[])
    ap.add_argument("--show", default="", help="fact ids to print question by question")
    args = ap.parse_args(argv)

    script = json.loads(args.script.read_text(encoding="utf-8"))
    res = bench(args.db, script, cue=args.cue, skip_card=args.skip_card, pages=args.pages,
                vectors=args.vectors,
                show=set(filter(None, args.show.split(","))))
    asked, missing = res["asked"], res["missing"]
    cue = {"his": "只用他这句", "his+hers": "他这句 + 她上一句",
           "chat": "他这句，太短才加她上一句"}[args.cue]
    print(f"\n{script['name']}：{asked} 问；到问的那天答案根本没记下的 {missing} 问（哪种找法都救不了）。")
    if res["no_her_line"]:
        print(f"（有 {res['no_her_line']} 问在库里找不到这句话，只用了他这句；库和剧本对不上？）")
    card = "，底牌上的算找到、不占名额" if args.skip_card else ""
    print(f"其余 {asked - missing} 问里，答案排进前 {DEFAULT_K}（{cue}{card}；不管遗忘）：")
    for name, n in res["totals"].items():
        print(f"  {name}: {n} / {asked - missing}")
    if args.pages:
        print(f"再加上翻聊天摘要，全部 {asked} 问里摆到她面前的（没记成笔记的 {missing} 问里翻到 {res['rescued']} 问）：")
        for name, n in res["with_pages"].items():
            print(f"  {name} + 翻摘要: {n} / {asked}")
        g = res["gate"]
        print(f"他的 {g['lines']} 句话里，{g['opened']} 句会去翻（{100 * g['opened'] / max(1, g['lines']):.0f}%），"
              f"{g['paged']} 句真翻到了；翻出来的东西里秘密 {g['secrets']} 处。")


if __name__ == "__main__":
    main()

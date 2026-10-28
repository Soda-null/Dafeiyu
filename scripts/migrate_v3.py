#!/usr/bin/env python3
"""Move a memory v2 database to memory v3 (design step 9, docs/memory_v3_zh.md §8). No model
calls, no money, nothing ever deleted.

A dry run by default: every step is worked out on a copy held in memory and printed; the file
is not touched, not even its columns. --apply first backs the file up next to it
(fish.db.bak-v2; an older backup is never overwritten), then writes, all in one transaction.
Stop the fish (scripts/fish.sh, the box's service) before --apply.

What needs the user's eye is only listed, and done only for the ids given (also in a dry run,
so the result can be looked at first):
  --pacts 17,3|all       make these promises between them / his nickname for her (step 6)
  --subjects 123|all     her own doings a merge handed to him: the leading 他 becomes 我 (step 4)
  --dates 45|all         a date that disagrees with the weekday next to it moves to it (§B2 D5)
  --ceilings unasked|all the old 没问成 events down to 14 days; all: 路过 and 待印证 rules to
                         their ceilings too (step 7; the numbers wait for the user, §11 item 2)

  .venv/bin/python scripts/migrate_v3.py [--db data/fish.db] [--apply] [--now 2027-04-01T12:00]
        [--pacts ...] [--subjects ...] [--dates ...] [--ceilings unasked|all]

--now: the moment the weekday patterns are counted at (his last 56 days before it); a
checkup database lives in its script's year, so give it the time of its last message.
What it prints is her memories, word for word: for the terminal only, never into the repo.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fish.brain.consolidate import keeps_subject  # noqa: E402
from fish.memory import pacts as pk  # noqa: E402
from fish.memory import stability as st  # noqa: E402
from fish.memory.longterm import (UNASKED, MemoryStore, _from_row, ceiling_of, strongest_about,  # noqa: E402
                                  why_before_v3)
from fish.memory.pages import keys_of  # noqa: E402
from fish.memory.patterns import DAY_ENDS, count_patterns  # noqa: E402
from fish.memory.relationship import Relationship  # noqa: E402
from fish.memory.when import day_of, fix_weekday, written_day  # noqa: E402
from fish.storage.db import init_schema  # noqa: E402

KEPT = ("memories", "messages", "episodes", "prospective", "diary")  # never fewer rows after
HER_SUBJECT = re.compile(r"^(\s*)[他她]")
SHOWN_CHARS = 48
WHO_SAID = {"him": "他答应的", "her": "她答应的", "both": "说好的"}


@dataclass
class Step:
    title: str
    lines: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)  # waiting for the user's say
    note: str = ""
    how: str = "给编号才做"  # how the user says yes to the candidates


def short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= SHOWN_CHARS else text[:SHOWN_CHARS] + "…"


def ids_arg(value: str | None) -> set[int] | str | None:
    """"17,3" -> {17, 3}; "all" stays "all"; None: nothing given."""
    if value is None or value == "all":
        return value
    return {int(v) for v in value.split(",") if v.strip()}


def chosen(i: int, wanted: set[int] | str | None) -> bool:
    return wanted == "all" or (isinstance(wanted, set) and i in wanted)


def _rows(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> list:
    return list(map(_from_row, conn.execute(sql, args)))


def _episodes(conn: sqlite3.Connection) -> dict[int, sqlite3.Row]:
    return {r["id"]: r for r in conn.execute("SELECT * FROM episodes")}


def written_at_close(m, ep: sqlite3.Row | None) -> bool:
    """Before v3 step 1 a close dated its notes when it ran (the next message, or 03:30 at night),
    after the chat's last message and up to the moment the chat was marked ended. A correction
    keeps the corrected note's chat but is written in a later one, after that chat ended."""
    return (ep is not None and not m.merged_from and ep["ended"] is not None
            and ep["last_active"] < m.created <= ep["ended"])


# --- the steps, in the order of §8 ----------------------------------------------------------

def add_columns(conn: sqlite3.Connection) -> Step:
    """1. The new columns; running it again adds nothing."""
    tables = ("memories", "prospective", "episodes")
    before = {t: {r[1] for r in conn.execute(f"PRAGMA table_info({t})")} for t in tables}
    init_schema(conn)
    step = Step("1. 加新列")
    for t, cols in before.items():
        added = [r[1] for r in conn.execute(f"PRAGMA table_info({t})") if r[1] not in cols]
        if added:
            step.lines.append(f"{t}: {', '.join(added)}")
    step.note = "" if step.lines else "都已经有了"
    return step


def fill_why(conn: sqlite3.Connection) -> Step:
    """2. Why each replaced memory was replaced: a source of a merge -> merge; a rule replaced by
    a rule of its kind, not merged -> cap; anything else -> update (longterm.why_before_v3)."""
    step = Step("2. 换掉的旧条补上为什么")
    counts: dict[str, list[int]] = {}
    for old in _rows(conn, "SELECT * FROM memories WHERE superseded_by IS NOT NULL AND why IS NULL ORDER BY id"):
        new = _from_row(conn.execute("SELECT * FROM memories WHERE id = ?", (old.superseded_by,)).fetchone())
        why = why_before_v3(old, new)
        conn.execute("UPDATE memories SET why = ? WHERE id = ?", (why, old.id))
        counts.setdefault(why, []).append(old.id)
    for why, ids in sorted(counts.items()):
        more = " …" if len(ids) > 12 else ""
        step.lines.append(f"{why}: {len(ids)} 条（#{', #'.join(map(str, ids[:12]))}{more}）")
    step.note = "" if counts else "没有要补的"
    return step


def fill_about(conn: sqlite3.Connection) -> Step:
    """3. A merged memory with no about: the strongest about among its sources, back through
    merges of merges; still unconfirmed only when every source was."""
    step = Step("3. 合并出来的条补上\"说的是什么那一档\"")
    resolved: dict[int, str | None] = {}

    def about_of(i: int) -> str | None:
        if i not in resolved:
            row = conn.execute("SELECT about, merged_from FROM memories WHERE id = ?", (i,)).fetchone()
            if row is None:
                resolved[i] = None
            elif row["about"]:
                resolved[i] = row["about"]
            else:
                resolved[i] = None  # a cycle cannot happen, but never loop
                sources = json.loads(row["merged_from"] or "[]")
                resolved[i] = strongest_about([about_of(s) for s in sources]) if sources else None
        return resolved[i]

    for m in _rows(conn, "SELECT * FROM memories WHERE about IS NULL AND merged_from IS NOT NULL"
                         " AND merged_from != '[]' ORDER BY id"):
        about = about_of(m.id)
        if about is not None:
            conn.execute("UPDATE memories SET about = ? WHERE id = ?", (about, m.id))
            step.lines.append(f"#{m.id} → {about}{'' if m.alive else '（已换掉）'}：{short(m.text)}")
    step.note = "" if step.lines else "没有要补的"
    return step


def fix_subjects(conn: sqlite3.Connection, wanted) -> Step:
    """4. Her own doings that came back as "他……": a self note, an old "他一直没问成他", a merge of
    notes that all began with 我. Listed; only the ids given get their leading 他 as 我."""
    step = Step("4. 她自己的事被写成了\"他……\"（要你确认，--subjects）")
    for m in _rows(conn, "SELECT * FROM memories WHERE superseded_by IS NULL ORDER BY id"):
        if not HER_SUBJECT.match(m.text):
            continue
        sources = tuple(_rows(conn, f"SELECT * FROM memories WHERE id IN ({', '.join('?' * len(m.merged_from))})",
                              m.merged_from)) if m.merged_from else ()
        if not (m.kind == "self" or UNASKED.search(m.text) or (sources and not keeps_subject(sources, m.text))):
            continue
        fixed = HER_SUBJECT.sub(r"\1我", m.text, count=1)
        if chosen(m.id, wanted):
            pattern = HER_SUBJECT.sub(r"\1我", m.pattern, count=1) if m.pattern else None
            conn.execute("UPDATE memories SET text = ?, pattern = ? WHERE id = ?", (fixed, pattern, m.id))
            step.lines.append(f"#{m.id} 改成：{short(fixed)}")
        else:
            step.candidates.append(f"#{m.id} {m.kind}：{short(m.text)}")
    step.note = "" if step.lines or step.candidates else "没有"
    return step


def fix_dates(conn: sqlite3.Connection, wanted) -> Step:
    """D5. A date that disagrees with the weekday written next to it (#45 "2027-01-24周六"):
    the weekday wins, within 3 days. Changes the words, so only for the ids given."""
    step = Step("5a. 日期和周几对不上的（要你确认，--dates）")
    for m in _rows(conn, "SELECT * FROM memories WHERE superseded_by IS NULL ORDER BY id"):
        fixed = fix_weekday(m.text, datetime.fromisoformat(m.created).date())
        if fixed == m.text:
            continue
        if chosen(m.id, wanted):
            conn.execute("UPDATE memories SET text = ? WHERE id = ?", (fixed, m.id))
            step.lines.append(f"#{m.id} 改成：{short(fixed)}")
        else:
            step.candidates.append(f"#{m.id}：{short(m.text)} → {short(fixed)}")
    step.note = "" if step.lines or step.candidates else "没有"
    return step


def her_day(ts: datetime) -> date:
    """The day of hers a moment belongs to: the night at 03:30 still closes the day before."""
    return ts.date() - timedelta(days=1) if ts.time() <= DAY_ENDS else ts.date()


def his_line_before(conn: sqlite3.Connection, episode_id: int, at: str) -> str:
    row = conn.execute("SELECT text FROM messages WHERE episode_id = ? AND role = 'user' AND ts <= ?"
                       " ORDER BY ts DESC, id DESC LIMIT 1", (episode_id, at)).fetchone()
    return row["text"] if row else ""


def fill_happened_on(conn: sqlite3.Connection) -> Step:
    """5. The day each memory is about, the way v3 writes it: a merge, the date its words write
    or else the latest of its sources'; a note from a chat, the one day it (or, for an event, his
    line) names, else that day; a note a close wrote, the same but at the chat's last message,
    which also becomes when it was written (v3 step 1: a close dates its notes at the chat, not
    at 03:30 the next night); a correction, its own day or else the corrected one's; a note of
    the night or her own time, the day its words name read on her day (the night's "明天" is
    the day after the one it closes), else the day it was written."""
    step = Step("5b. 补上\"事情是哪天\"")
    eps = _episodes(conn)
    counts = {"合并": 0, "聊天里记的": 0, "收尾记的": 0, "改口": 0, "夜里和别处": 0}
    moved = named = 0
    for m in _rows(conn, "SELECT * FROM memories WHERE happened_on IS NULL ORDER BY id"):
        created = datetime.fromisoformat(m.created)
        ep = eps.get(m.source_episode) if m.source_episode is not None else None
        sets: dict[str, object] = {}
        if m.merged_from:
            olds = _rows(conn, f"SELECT * FROM memories WHERE id IN ({', '.join('?' * len(m.merged_from))})",
                         m.merged_from)
            latest = max((datetime.fromisoformat(o.created) for o in olds), default=created)
            d = written_day(m.text, latest.date())
            day = d.isoformat() if d else max((o.happened_on for o in olds if o.happened_on), default=None)
            counts["合并"] += 1
        elif ep is not None and written_at_close(m, ep):
            at = datetime.fromisoformat(ep["last_active"])
            d = day_of(m.text, at)
            day = (d or at.date()).isoformat()
            sets["created"] = ep["last_active"]
            if m.times == 1 and m.last_time == m.created[:10]:
                sets["last_time"] = ep["last_active"][:10]
            moved += m.created[:10] != ep["last_active"][:10]
            counts["收尾记的"] += 1
        elif ep is not None and ep["ended"] is not None and m.created > ep["ended"]:
            old = conn.execute("SELECT happened_on FROM memories WHERE superseded_by = ? ORDER BY id DESC LIMIT 1",
                               (m.id,)).fetchone()
            d = day_of(m.text, created)
            day = d.isoformat() if d else ((old["happened_on"] if old else None) or created.date().isoformat())
            counts["改口"] += 1
        elif ep is not None:
            said = his_line_before(conn, ep["id"], m.created) if m.kind == "event" else ""
            d = day_of(m.text, created, said)
            day = (d or created.date()).isoformat()
            counts["聊天里记的"] += 1
        else:
            d = day_of(m.text, datetime.combine(her_day(created), time(12)))
            day = (d or created.date()).isoformat()
            counts["夜里和别处"] += 1
        day = day or created.date().isoformat()
        named += day != str(sets.get("created", m.created))[:10]
        sets["happened_on"] = day
        cols = ", ".join(f"{c} = ?" for c in sets)
        conn.execute(f"UPDATE memories SET {cols} WHERE id = ?", (*sets.values(), m.id))
    total = sum(counts.values())
    if total:
        step.lines.append("，".join(f"{k} {v}" for k, v in counts.items() if v) + f"，共 {total} 条")
        step.lines.append(f"其中 {named} 条的那天和记下的日子不一样；"
                          f"收尾记的里 {moved} 条记下的日子挪回那次聊天的日子")
    step.note = "" if total else "都已经有了"
    return step


def find_pacts(conn: sqlite3.Connection, wanted) -> Step:
    """6. The promise and nickname words (pacts.py) over the live memories. Heard from him (the
    note has a chat) and not: the night and her browsing write in the same words ("我答应上午给他
    带点好玩的事"), and the nickname only ever reached her as a rule. Only the ids given become
    pacts: pinned, 一辈子; a promise open, his nickname for her a fact."""
    step = Step("6. 认出来的承诺和外号（要你确认，--pacts）")
    for m in _rows(conn, "SELECT * FROM memories WHERE superseded_by IS NULL AND pact IS NULL"
                         " AND kind != 'world' ORDER BY id"):
        nick = pk.nickname(m.text)
        who = None if nick else pk.promise(m.text, m.kind)
        if not nick and who is None:
            continue
        what = "外号" if nick else f"承诺（{WHO_SAID[who]}）"
        heard = "" if m.source_episode is not None else "，不是听他说的（夜里或她自己写的）"
        if chosen(m.id, wanted):
            kind, pact, state = ("fact", "both", None) if nick else (m.kind, who, "open")
            conn.execute("UPDATE memories SET kind = ?, about = '一辈子', pact = ?, pact_state = ?, pinned = 1,"
                         " stability = ?, importance = ? WHERE id = ?",
                         (kind, pact, state, st.INFINITE, st.PINNED_IMPORTANCE, m.id))
            step.lines.append(f"#{m.id} 设成{what}：{short(m.text)}")
        else:
            step.candidates.append(f"#{m.id} {m.kind} {what}{heard}：{short(m.text)}")
    step.note = "" if step.lines or step.candidates else "没有"
    return step


def lower_ceilings(conn: sqlite3.Connection, which: str | None) -> Step:
    """7. Old memories above the ceilings §4 sets: the old 没问成 events (unasked), and with
    "all" also the 路过 notes and the 待印证 rules. Nothing is cut without --ceilings."""
    step = Step("7. 牢固度压到上限以下（要你批准 §4 的数字，--ceilings）",
                how="--ceilings unasked 或 all 才做")
    over = []
    for m in _rows(conn, "SELECT * FROM memories WHERE superseded_by IS NULL AND pinned = 0 ORDER BY id"):
        top = ceiling_of(m.kind, m.text, m.about)
        if m.stability > top:
            over.append((m, top, "unasked" if UNASKED.search(m.text) else "all"))
    for m, top, group in over:
        line = f"#{m.id} {m.about or m.kind} {m.stability:.0f} → {top:.0f} 天：{short(m.text)}"
        if which == "all" or which == group:
            conn.execute("UPDATE memories SET stability = ? WHERE id = ?", (top, m.id))
            step.lines.append(line)
        else:
            step.candidates.append(f"[{'没问成' if group == 'unasked' else '路过/待印证'}] {line}")
    step.note = "" if over else "没有超的"
    return step


def link_followups(conn: sqlite3.Connection) -> Step:
    """8. An open follow-up with no memory behind it: an open promise it overlaps, else the
    note of the chat it was written in that it is about (as respond.add_followup does now)."""
    step = Step("8. 开着的惦记补上\"从哪条记忆来\"")
    store = MemoryStore(conn)
    eps = sorted(_episodes(conn).values(), key=lambda r: r["started"])
    for f in conn.execute("SELECT * FROM prospective WHERE status = 'open' AND source_memory IS NULL"
                          " ORDER BY id").fetchall():
        ep = next((e for e in reversed(eps) if e["started"] <= f["created"] <= (e["ended"] or e["last_active"])), None)
        about = store.pact_for(f["text"]) or (store.source_for(f["text"], ep["id"]) if ep is not None else None)
        if about is not None:
            conn.execute("UPDATE prospective SET source_memory = ? WHERE id = ?", (about.id, f["id"]))
            step.lines.append(f"惦记 {f['id']}「{short(f['text'])}」→ #{about.id} {short(about.text)}")
    step.note = "" if step.lines else "没有能补的"
    return step


def fill_keys(conn: sqlite3.Connection) -> Step:
    """9a. Each closed chat's keys: the tags and 《names》 of the notes it left (pages.keys_of),
    replaced ones too: the chat was about them when it closed."""
    step = Step("9. 每次聊天补上标签，再数一次规律")
    eps = conn.execute("SELECT id, last_active, ended FROM episodes WHERE ended IS NOT NULL AND keys IS NULL"
                       " ORDER BY id").fetchall()
    with_keys = 0
    for e in eps:
        left = _rows(conn, "SELECT * FROM memories WHERE source_episode = ? AND created <= ?"
                           " AND (merged_from IS NULL OR merged_from = '[]') ORDER BY id", (e["id"], e["ended"]))
        keys = keys_of(left)
        with_keys += bool(keys)
        conn.execute("UPDATE episodes SET keys = ? WHERE id = ?", (json.dumps(keys, ensure_ascii=False), e["id"]))
    if eps:
        step.lines.append(f"{len(eps)} 次聊天，{with_keys} 次有标签")
    return step


def count_once(conn: sqlite3.Connection, now: datetime, step: Step) -> Step:
    """9b. The weekday patterns, counted once now so the first day after has them (the night
    counts them again each time)."""
    rel = Relationship(conn)
    if conn.execute("SELECT 1 FROM relationship WHERE key = 'patterns'").fetchone():
        step.lines.append("规律已经数过，不重数")
    else:
        patterns = count_patterns(conn, now, [])
        rel.set_patterns(patterns, now)
        found = [f"周{'一二三四五六日'[p['weekday']]} · {p['phrase']}（{p['status']}）" for p in patterns]
        step.lines.append(f"规律（按 {now:%Y-%m-%d %H:%M} 往前 56 天数）：{'；'.join(found) or '没有'}")
    if not step.lines:
        step.note = "都已经有了"
    return step


# --- running it ---------------------------------------------------------------------------

def sizes(conn: sqlite3.Connection) -> dict[str, int]:
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in KEPT}


def migrate(conn: sqlite3.Connection, now: datetime, *, pacts=None, subjects=None, dates=None,
            ceilings: str | None = None) -> list[Step]:
    """Every step on this connection, in one transaction; committed only by the caller. Raises
    if any table ended with fewer rows than it began with."""
    conn.row_factory = sqlite3.Row
    before = sizes(conn)
    steps = [add_columns(conn)]
    steps += [fill_why(conn), fill_about(conn), fix_subjects(conn, subjects), fix_dates(conn, dates),
              fill_happened_on(conn), find_pacts(conn, pacts), lower_ceilings(conn, ceilings),
              link_followups(conn)]
    keys = fill_keys(conn)
    after = sizes(conn)
    lost = {t: (before[t], after[t]) for t in KEPT if after[t] < before[t]}
    if lost:
        raise RuntimeError(f"rows would be lost, nothing written: {lost}")
    return steps + [count_once(conn, now, keys)]  # last: it commits


def backup(db: Path) -> Path:
    """db.bak-v2 next to it; when that exists (a run before), db.bak-v2.1, .2, ...: an older
    backup is never overwritten."""
    target = db.with_name(db.name + ".bak-v2")
    n = 0
    while target.exists():
        n += 1
        target = db.with_name(f"{db.name}.bak-v2.{n}")
    src, dst = sqlite3.connect(db), sqlite3.connect(target)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    return target


def run(db: Path, now: datetime, *, apply: bool = False, **choices) -> tuple[list[Step], Path | None]:
    """Dry run: on a copy in memory, the file untouched. apply: back up, then write."""
    if not db.exists():
        raise FileNotFoundError(db)
    if not apply:
        src, conn = sqlite3.connect(db), sqlite3.connect(":memory:")
        src.backup(conn)
        src.close()
        steps = migrate(conn, now, **choices)
        conn.close()
        return steps, None
    saved = backup(db)
    conn = sqlite3.connect(db)
    try:
        steps = migrate(conn, now, **choices)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return steps, saved


def report(steps: list[Step], saved: Path | None) -> str:
    out = ["预演：文件没动。加 --apply 才写（先备份）。" if saved is None else f"已写入；备份在 {saved}"]
    for s in steps:
        out.append(f"\n{s.title}" + (f"：{s.note}" if s.note else ""))
        out += [f"  {line}" for line in s.lines]
        if s.candidates:
            out.append(f"  候选 {len(s.candidates)} 条，没动（{s.how}）：")
            out += [f"    {c}" for c in s.candidates]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "fish.db")
    ap.add_argument("--apply", action="store_true", help="write (after a backup); without it a dry run")
    ap.add_argument("--now", type=datetime.fromisoformat, default=None)
    ap.add_argument("--pacts")
    ap.add_argument("--subjects")
    ap.add_argument("--dates")
    ap.add_argument("--ceilings", choices=("unasked", "all"))
    a = ap.parse_args()
    steps, saved = run(a.db, a.now or datetime.now(), apply=a.apply, pacts=ids_arg(a.pacts),
                       subjects=ids_arg(a.subjects), dates=ids_arg(a.dates), ceilings=a.ceilings)
    print(report(steps, saved))


if __name__ == "__main__":
    main()

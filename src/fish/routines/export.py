"""data/notebook_export.md: a readable dump of what she remembers (decision 6, item 5)."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from fish.config import owner_words
from fish.memory import (Diary, EpisodeManager, MemoryStore, PhaseStore, ProspectiveStore, Relationship,
                         TraitStore)


def clarity(m, now: datetime) -> str:
    if m.pinned:
        return "钉住"
    r = m.retrievability(now)
    return "想不起" if r < 0.1 else "模糊" if r < 0.5 else "清楚"


def render_notebook(conn: sqlite3.Connection, now: datetime) -> str:
    store = MemoryStore(conn)
    lines = [f"# 大肥鱼的小本本（{now.strftime('%Y-%m-%d %H:%M')} 导出）", "",
             "> 她记得的东西。只给你看，不要改；改她要改 docs/persona_zh.md 或提示词。", "",
             "## 底牌"]
    lines += [f"- [#{m.id}] {m.text}" for m in store.profile()] or ["（还没有）"]
    lines += ["", owner_words("## 和他相处的方式")]
    lines += [f"- [#{m.id}] {m.text}" for m in store.howto_card()] or ["（还在摸索）"]
    lines += ["", "## 长期条目"]
    for m in store.alive():
        lines.append(f"- [#{m.id}] {m.kind} 重要{m.importance} {clarity(m, now)}  {m.text}")
    lines += ["", "## 惦记"]
    lines += [f"- {f.due}  {f.text}" for f in ProspectiveStore(conn).open()] or ["（没有）"]
    lines += ["", "## 最近的聊天"]
    lines += [f"- {ep.started[:16]}  {ep.gist or ep.summary[:60]}" for ep in EpisodeManager(conn).recent(7)] or ["（还没有）"]
    lines += ["", "## 日记"]
    lines += [f"- {day}  {text}" for day, text in Diary(conn).recent(7)] or ["（还没写过）"]
    rel = Relationship(conn)
    stats = rel.stats(now)
    phase = PhaseStore(conn).current()
    traits = TraitStore(conn)
    lines += ["", f"认识 {stats['days_known']} 天，聊过 {stats['days_talked']} 天，连着 {stats['streak']} 天，亲近 {rel.closeness:.0f}。",
              f"这阵子的她：{phase.line or '（还没写）'}（基调{phase.tone_word}，劲头{phase.drive_word}）",
              f"底色：{'；'.join(traits.describe()) or '还是刚认识时的样子'}", ""]
    return "\n".join(lines)


def export_notebook(conn: sqlite3.Connection, now: datetime, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_notebook(conn, now), encoding="utf-8")
    return path

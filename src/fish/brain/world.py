"""Her browsing, the model side (docs/world_design_zh.md §4): pick what to open, then
turn what she read into 见闻 (world memories) in her own voice."""

from __future__ import annotations

from dataclasses import dataclass

from fish.brain.ask import ask_json
from fish.brain.llm import LLM
from fish.memory import stability as st
from fish.world import Item

MAX_PICKS = 3
SEEN_IMPORTANCE = (1, 6)
SELF_NOTE_IMPORTANCE = (3, 5)


@dataclass(frozen=True)
class Seen:
    index: int
    text: str
    importance: int
    valence: float
    tags: tuple[str, ...]


def _lines(items: list[str], empty: str) -> str:
    return "\n".join(f"- {i}" for i in items) or empty


def _clamp(v, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


class Browser:
    def __init__(self, llm: LLM, persona: str) -> None:
        self.llm = llm
        self.persona = persona

    def pick(self, items: list[Item], *, day: str, threads: list[str], topics: list[str]) -> list[int]:
        if not items:
            return []
        listing = "\n".join(f"{i}. 【{it.source}·{it.flavor}】{it.title}" + (f" —— {it.summary[:80]}" if it.summary else "")
                            for i, it in enumerate(items))
        data = ask_json(self.llm, "browse_pick", persona=self.persona, day=day,
                        threads=_lines(threads, "（没什么特别的）"), topics=_lines(topics, "（最近没聊）"),
                        items=listing, temperature=0.9)
        picks: list[int] = []
        for p in (data or {}).get("picks") or []:
            n = p.get("n") if isinstance(p, dict) else None
            if isinstance(n, int) and 0 <= n < len(items) and n not in picks:
                picks.append(n)
        return picks[:MAX_PICKS]

    def read(self, opened: list[tuple[Item, str]]) -> tuple[list[Seen], list[tuple[str, int]]]:
        if not opened:
            return [], []
        blocks = "\n\n".join(f"{i}. 【{it.source}】{it.title}（{it.url}）\n{text}" for i, (it, text) in enumerate(opened))
        data = ask_json(self.llm, "browse_read", persona=self.persona, opened=blocks, temperature=0.9,
                        max_tokens=900)
        seen: list[Seen] = []
        for s in (data or {}).get("seen") or []:
            if not isinstance(s, dict):
                continue
            n = s.get("n")
            text = str(s.get("text", "")).strip()[:200]
            if isinstance(n, int) and 0 <= n < len(opened) and text:
                tags = s.get("tags") if isinstance(s.get("tags"), list) else []
                try:
                    valence = max(-1.0, min(1.0, float(s.get("valence", 0))))
                except (TypeError, ValueError):
                    valence = 0.0
                seen.append(Seen(n, text, _clamp(s.get("importance"), *SEEN_IMPORTANCE, default=3),
                                 valence, tuple(str(t).strip() for t in tags if str(t).strip())[:3]))
        notes = [(str(n["text"]).strip()[:200], _clamp(n.get("importance"), *SELF_NOTE_IMPORTANCE, default=4))
                 for n in (data or {}).get("self_notes") or []
                 if isinstance(n, dict) and str(n.get("text", "")).strip()]
        return seen, notes[:3]


def importance_ok(v: int) -> int:
    return st.clamp_importance(v)

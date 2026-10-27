"""The night's model calls (docs/memory_design_zh.md §5.4): merge duplicates, spot
contradictions, reflect, write her diary. Each is one call that returns JSON; a bad reply
means "do nothing tonight", never an exception, so the mechanical steps still run.
"""

from __future__ import annotations

from dataclasses import dataclass

from fish.brain.llm import LLM
from fish.brain.parse import extract_json
from fish.brain.prompt import load_template, render
from fish.memory import Memory
from fish.memory import stability as st

DIARY_MAX_CHARS = 120
INSIGHT_IMPORTANCE = (6, 8)
SELF_NOTE_IMPORTANCE = (3, 5)


def _clamp(v, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def _lines(items: list[str], empty: str) -> str:
    return "\n".join(f"- {i}" for i in items) or empty


@dataclass(frozen=True)
class Merge:
    ids: tuple[int, ...]
    text: str


@dataclass(frozen=True)
class Update:
    old_id: int
    new_id: int


class Consolidator:
    def __init__(self, llm: LLM, persona: str) -> None:
        self.llm = llm
        self.persona = persona

    def _ask(self, template: str, *, temperature: float = 0.5, max_tokens: int = 800,
             **fields: str) -> dict | None:
        content = render(load_template(template), **fields)
        try:
            raw = self.llm.chat([{"role": "user", "content": content}], json_mode=True,
                                temperature=temperature, max_tokens=max_tokens)
        except Exception:  # noqa: BLE001 - the night must go on without the model
            return None
        return extract_json(raw)

    def merge_pairs(self, pairs: list[tuple[Memory, Memory]]) -> list[Merge]:
        if not pairs:
            return []
        text = "\n\n".join(f"对 {i + 1}：\n- [#{a.id}] {a.text}\n- [#{b.id}] {b.text}"
                           for i, (a, b) in enumerate(pairs))
        data = self._ask("merge", pairs=text)
        allowed = {frozenset((a.id, b.id)) for a, b in pairs}
        merges: list[Merge] = []
        for item in (data or {}).get("merges") or []:
            if not isinstance(item, dict):
                continue
            ids = item.get("ids")
            merged = str(item.get("text", "")).strip()
            if (isinstance(ids, list) and len(ids) == 2 and all(isinstance(i, int) for i in ids)
                    and frozenset(ids) in allowed and merged):
                merges.append(Merge(tuple(ids), merged[:200]))
        return merges

    def find_updates(self, groups: list[tuple[Memory, list[Memory]]]) -> list[Update]:
        """groups: (new fact, older facts it might replace)."""
        if not groups:
            return []
        text = "\n\n".join(
            f"新：[#{new.id}] {new.text}\n旧：\n" + "\n".join(f"- [#{o.id}] {o.text}" for o in olds)
            for new, olds in groups)
        data = self._ask("contradictions", groups=text)
        allowed = {(o.id, new.id) for new, olds in groups for o in olds}
        updates: list[Update] = []
        for item in (data or {}).get("updates") or []:
            if isinstance(item, dict) and (item.get("old_id"), item.get("new_id")) in allowed:
                updates.append(Update(item["old_id"], item["new_id"]))
        return updates

    def reflect(self, gists: list[str], facts: list[Memory], old_insights: list[str],
                old_howto: list[str] | None = None) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
        """Returns (insights, howto rules), each (text, importance)."""
        data = self._ask("reflect", persona=self.persona, gists=_lines(gists, "（最近没怎么聊）"),
                         facts=_lines([f.text for f in facts], "（还不多）"),
                         old_insights=_lines(old_insights, "（还没有）"),
                         old_howto=_lines(old_howto or [], "（还没有）"))

        def take(key: str, limit: int) -> list[tuple[str, int]]:
            out: list[tuple[str, int]] = []
            for item in (data or {}).get(key) or []:
                if isinstance(item, dict) and str(item.get("text", "")).strip():
                    out.append((str(item["text"]).strip()[:200],
                                _clamp(item.get("importance"), *INSIGHT_IMPORTANCE, default=6)))
            return out[:limit]

        return take("insights", 3), take("howto", 2)

    def diary(self, day: str, mood: str, threads: list[str], gists: list[str],
              yesterday: str, seen: list[str] | None = None, *, phase_line: str = "",
              tone_word: str = "一般", drive_word: str = "还行") -> tuple[str, list[tuple[str, int]], str]:
        """Returns (diary text, new life threads, the phase line: how she has been lately)."""
        data = self._ask("diary", persona=self.persona, day=day, mood=mood,
                         threads=_lines(threads, "（还没有，可以开始一件）"),
                         gists=_lines(gists, "（今天没聊）"), yesterday=yesterday or "（没写）",
                         seen=_lines(seen or [], "（今天没逛）"),
                         phase_line=phase_line or "（还没写过）", tone_word=tone_word, drive_word=drive_word)
        if not data or not str(data.get("diary", "")).strip():
            return "", [], ""
        notes = [(str(n["text"]).strip()[:200], _clamp(n.get("importance"), *SELF_NOTE_IMPORTANCE, default=4))
                 for n in (data.get("self_notes") or []) if isinstance(n, dict) and str(n.get("text", "")).strip()]
        line = str(data.get("phase_line") or data.get("recent") or "").strip()[:60]
        return str(data["diary"]).strip()[:DIARY_MAX_CHARS], notes[:3], line

    def grow(self, day: str, days_known: int, diary: list[str], phases: list[str],
             traits: list[str]) -> tuple[str, dict[str, float]]:
        """Her monthly look back (layer A): a note in her words and small slider moves."""
        data = self._ask("growth", persona=self.persona, day=day, days_known=str(days_known),
                         diary=_lines(diary, "（这个月没写）"), phases=_lines(phases, "（没记录）"),
                         traits=_lines(traits, "（无）"), temperature=0.7)
        if not data:
            return "", {}
        note = str(data.get("note") or "").strip()[:120]
        changes = data.get("changes") if isinstance(data.get("changes"), dict) else {}
        return note, {str(k): v for k, v in changes.items()}


def similarity(a: str, b: str) -> float:
    """Dice overlap of character bigrams, the same measure recall uses without a model."""
    from fish.memory.retrieval import BigramEmbedder

    x, y = BigramEmbedder.bigrams(a), BigramEmbedder.bigrams(b)
    if not x or not y:
        return 0.0
    return 2 * len(x & y) / (len(x) + len(y))


def importance_for_merge(m: Memory) -> int:
    return st.clamp_importance(m.importance)

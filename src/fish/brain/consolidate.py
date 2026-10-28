"""The night's model calls (docs/memory_design_zh.md §5.4): merge duplicates, spot
contradictions, rewrite often-repeated things as gists (decision 20), reflect, write her diary. Each is one call that returns JSON; a bad reply
means "do nothing tonight", never an exception, so the mechanical steps still run. A rewrite
that holds a secret (memory.scrub) is dropped; the diary loses such a sentence when written.
"""

from __future__ import annotations

from dataclasses import dataclass

from fish.brain.llm import LLM
from fish.brain.parse import extract_json
from fish.brain.prompt import load_template, render
from fish.memory import Memory, secret
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


def keeps_subject(sources: tuple[Memory, ...], merged: str) -> bool:
    """A merge must not hand her own doings to him: her life threads, or two notes that both
    start with 我 ("我一直没问成他"), never come back as "他……" (memory v3 step 1)."""
    if not merged.lstrip().startswith(("他", "她")):
        return True
    return not (any(m.kind == "self" for m in sources)
                or all(m.text.lstrip().startswith("我") for m in sources))


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
        # each with the day it was written: the later one says how things are now (memory v3 §14)
        text = "\n\n".join(f"对 {i + 1}：\n- [#{a.id}]（{a.created[:10]} 记的）{a.text}\n"
                           f"- [#{b.id}]（{b.created[:10]} 记的）{b.text}"
                           for i, (a, b) in enumerate(pairs))
        data = self._ask("merge", pairs=text)
        allowed = {frozenset((a.id, b.id)): (a, b) for a, b in pairs}
        merges: list[Merge] = []
        for item in (data or {}).get("merges") or []:
            if not isinstance(item, dict):
                continue
            ids = item.get("ids")
            merged = str(item.get("text", "")).strip()
            if (isinstance(ids, list) and len(ids) == 2 and all(isinstance(i, int) for i in ids)
                    and frozenset(ids) in allowed and merged and not secret(merged)
                    and keeps_subject(allowed[frozenset(ids)], merged)):
                merges.append(Merge(tuple(ids), merged[:200]))
        return merges

    def gists(self, memories: list[Memory]) -> dict[int, str]:
        """Things that happened many times, each rewritten without one-off details."""
        if not memories:
            return {}
        items = "\n".join(f"- [#{m.id}]（{m.times} 回）{m.text}" for m in memories)
        data = self._ask("gist", items=items, temperature=0.3)
        allowed = {m.id for m in memories}
        out: dict[int, str] = {}
        for item in (data or {}).get("gists") or []:
            if (isinstance(item, dict) and item.get("id") in allowed and str(item.get("text", "")).strip()
                    and not secret(str(item["text"]))):
                out[item["id"]] = str(item["text"]).strip()[:80]
        return out

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

    def reflect(self, gists: list[str], facts: list[Memory], old_insights: list[Memory],
                old_howto: list[Memory] | None = None, *, newer: set[int] | frozenset[int] = frozenset()
                ) -> tuple[list[tuple[str, int]], list[tuple[str, int]], list[int], list[int]]:
        """Returns (insights, howto rules, outdated, confirms): new ones as (text, importance),
        the ids of old rules she now sees are no longer true (decision 21), and the ids of old
        rules she saw again in other words. `newer`: rules written during the chats she is
        looking back on; they are that same evidence, so they are neither outdated nor confirmed."""
        old_howto = old_howto or []

        def listed(ms: list[Memory]) -> str:
            return _lines([f"[#{m.id}] {m.line()}" + ("（新记的）" if m.id in newer else "") for m in ms],
                          "（还没有）")

        data = self._ask("reflect", persona=self.persona, gists=_lines(gists, "（最近没怎么聊）"),
                         facts=_lines([f.line() for f in facts], "（还不多）"),
                         old_insights=listed(old_insights), old_howto=listed(old_howto))
        known = ({m.id for m in old_insights} | {m.id for m in old_howto}) - set(newer)

        def ids(key: str) -> list[int]:
            got = (data or {}).get(key)
            if not isinstance(got, list):
                return []
            return list(dict.fromkeys(i for i in got if isinstance(i, int) and i in known))

        outdated = ids("outdated")
        confirms = [i for i in ids("confirms") if i not in outdated]

        def take(key: str, limit: int) -> list[tuple[str, int]]:
            out: list[tuple[str, int]] = []
            for item in (data or {}).get(key) or []:
                if isinstance(item, dict) and str(item.get("text", "")).strip():
                    out.append((str(item["text"]).strip()[:200],
                                _clamp(item.get("importance"), *INSIGHT_IMPORTANCE, default=6)))
            return out[:limit]

        return take("insights", 3), take("howto", 2), outdated, confirms

    def diary(self, day: str, mood: str, threads: list[str], gists: list[str],
              yesterday: str, seen: list[str] | None = None, *, phase_line: str = "",
              tone_word: str = "一般", drive_word: str = "还行",
              leisure: list[str] | None = None) -> tuple[str, list[tuple[str, int]], str]:
        """Returns (diary text, new life threads, the phase line: how she has been lately)."""
        data = self._ask("diary", persona=self.persona, day=day, mood=mood,
                         threads=_lines(threads, "（还没有，可以开始一件）"),
                         gists=_lines(gists, "（今天没聊）"), yesterday=yesterday or "（没写）",
                         seen=_lines(seen or [], "（今天没逛）"), leisure=_lines(leisure or [], "（没记下）"),
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

"""Recall: which long-term memories a line of conversation brings to mind (§5.2).

Two gates, then a score. A memory must first be retrievable: R >= FREE_RECALL_R on its own,
or R >= CUED_RECALL_R when the cue is strong (recognition beats recall). Survivors are
scored relevance x recency x importance, the Generative Agents triple, and the top few
within a character budget are returned and touched (recall makes memories stronger).
What is already in front of her every turn (her card of facts about him) is passed as `skip`
and takes none of the few places (memory v3 §B3).

Relevance comes from an Embedder. Version 1 needs no model: character-bigram overlap, and
a full hit when one of the memory's tags appears in the cue. A sentence-embedding version
plugs in behind the same protocol (open question Q3, decision 6).

The cue is his line only (`cue_for`): her own last line put "roommate" into "do you remember
what I promised you" and pushed the promise out. `mentioned` marks the card facts his line
touches, with a small table so "宫保鸡丁" reaches "he is allergic to peanuts".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fish.memory import stability as st
from fish.memory.longterm import Memory, MemoryStore, days_between

W_RELEVANCE, W_RECENCY, W_IMPORTANCE = 0.5, 0.2, 0.3
RECENCY_DECAY_PER_HOUR = 0.995
STRONG_CUE = 0.6  # relevance at or above this can wake a memory she could not recall alone
DEFAULT_K = 6
DEFAULT_BUDGET_CHARS = 400
# His line is too short to search with when, without these, fewer than SHORT_CUE characters
# are left ("对就那个", "然后呢"): then her previous line is what he is answering. Particles
# and a few adverbs only: characters that are also inside words (过敏, 记得) stay.
FILLER = set("的了吗呢吧啊呀哦嗯哈么嘛呗啦哇噢就也都还又很太这那个")
SHORT_CUE = 6
# Only for marking a card fact as touched: what someone allergic to X runs into without saying X.
ALLERGEN_CUES = {
    "花生": ("宫保鸡丁", "花生酱", "鱼皮花生"),
    "乳糖": ("牛奶", "奶茶", "拿铁", "芝士"),
    "海鲜": ("虾", "蟹"),
}


class Embedder(Protocol):
    def relevance(self, cue: str, memory: Memory) -> float:
        """0..1: how much the cue has to do with the memory."""
        ...


class BigramEmbedder:
    """No model. Dice overlap of character bigrams; 1.0 when a tag of the memory is in the cue."""

    @staticmethod
    def bigrams(text: str) -> set[str]:
        chars = [c for c in text if c.isalnum()]
        return {a + b for a, b in zip(chars, chars[1:])}

    def relevance(self, cue: str, memory: Memory) -> float:
        if any(len(t) >= 2 and t in cue for t in memory.tags):
            return 1.0
        a, b = self.bigrams(cue), self.bigrams(memory.text)
        if not a or not b:
            return 0.0
        return 2 * len(a & b) / (len(a) + len(b))


@dataclass(frozen=True)
class Recalled:
    memory: Memory
    retrievability: float  # before this recall touched it
    relevance: float
    score: float
    cued: bool  # only came back because the cue was strong ("哦对，你说过")
    fuzzy: bool  # she is unsure of it ("好像是……")
    former: Memory | None  # what she used to think, if this memory replaced another


def cue_for(his: str, hers: str = "") -> str:
    """What a turn searches with: his line; her previous line too only when his is too short
    to mean anything alone."""
    left = [c for c in his if c.isalnum() and c not in FILLER]
    return f"{his} {hers}" if hers and len(left) < SHORT_CUE else his


def mentioned(line: str, memories: list[Memory], embedder: Embedder | None = None) -> list[Memory]:
    """Which of these (her card) his line touches: a tag of it, a strong overlap, or a food
    that carries what he is allergic to. By words only; a time word touches nothing."""
    embedder = embedder or BigramEmbedder()
    out = []
    for m in memories:
        hit = embedder.relevance(line, m) >= STRONG_CUE or any(
            key in m.text + "".join(m.tags) and any(w in line for w in words)
            for key, words in ALLERGEN_CUES.items())
        if hit:
            out.append(m)
    return out


def recency(memory: Memory, now: datetime) -> float:
    hours = max(0.0, days_between(memory.last_recalled, now) * 24)
    return RECENCY_DECAY_PER_HOUR**hours


def recall(
    store: MemoryStore,
    cue: str,
    now: datetime | None = None,
    *,
    embedder: Embedder | None = None,
    k: int = DEFAULT_K,
    budget_chars: int = DEFAULT_BUDGET_CHARS,
    skip: set[int] | frozenset[int] = frozenset(),
) -> list[Recalled]:
    """skip: ids already in front of her (the card); they are neither returned nor touched."""
    now = now or datetime.now()
    embedder = embedder or BigramEmbedder()
    candidates: list[tuple[float, Memory, float, float, bool]] = []
    for m in store.alive():
        if m.id in skip:
            continue
        rel = embedder.relevance(cue, m)
        if rel <= 0:
            continue
        r = m.retrievability(now)
        if r >= st.FREE_RECALL_R:
            cued = False
        elif rel >= STRONG_CUE and r >= st.CUED_RECALL_R:
            cued = True
        else:
            continue
        score = W_RELEVANCE * rel + W_RECENCY * recency(m, now) + W_IMPORTANCE * m.importance / 10
        candidates.append((score, m, r, rel, cued))
    candidates.sort(key=lambda c: (c[0], c[1].id), reverse=True)

    chosen: list[Recalled] = []
    used = 0
    for score, m, r, rel, cued in candidates:
        if len(chosen) >= k:
            break
        if chosen and used + len(m.text) > budget_chars:
            break
        used += len(m.text)
        touched = store.touch(m.id, now)
        chosen.append(Recalled(touched, r, rel, score, cued, r < st.FUZZY_R, store.former(m.id)))
    return chosen

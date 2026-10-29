"""Night steps 1–3b: the chat that trailed off is closed, today's notes are taken stock of,
near-duplicates merged, a new fact replaces an old one, a new event of his rewrites a fact it
made untrue, things that kept happening become one gist each."""

from __future__ import annotations

from datetime import datetime

from fish.brain import similarity
from fish.memory import Memory, MemoryStore, overlap
from fish.routines.night.context import Night, fish_day

MERGE_SIMILARITY = 0.4  # bigram Dice; the model makes the final call, this only picks candidates
# "住 3 号楼" and "搬到了七号楼" must look alike to the update check: numerals become digits.
_NUMERALS = str.maketrans("〇零一二两三四五六七八九", "001223456789")
MAX_PAIRS = 10
MAX_CANDIDATES = 5


def _new_today(store: MemoryStore, day) -> list[Memory]:
    return [m for m in store.alive() if fish_day(datetime.fromisoformat(m.created)) == day]


def _merge_pairs(new: list[Memory], alive: list[Memory]) -> list[tuple[Memory, Memory]]:
    pairs: list[tuple[Memory, Memory]] = []
    seen: set[frozenset[int]] = set()
    for a in new:
        for b in alive:
            if a.id == b.id or a.kind != b.kind or frozenset((a.id, b.id)) in seen:
                continue
            if similarity(a.text, b.text) >= MERGE_SIMILARITY:
                pairs.append((a, b) if a.id > b.id else (b, a))
                seen.add(frozenset((a.id, b.id)))
    return pairs[:MAX_PAIRS]


def _update_groups(new: list[Memory], alive: list[Memory],
                   merged_away: set[int]) -> list[tuple[Memory, list[Memory]]]:
    """Each new fact with the older facts it might replace. No upper bound on likeness: a pair
    the merge step declined ("住 3 号楼" / "住七号楼") is exactly a changed fact. Any shared
    words or tag make a candidate; the model decides, and "拿不准就不列". An open promise is
    never one: only he can call it off, and the close of that chat says so (memory v3 §B4)."""
    groups = []
    for n in new:
        if n.kind != "fact" or n.id in merged_away:
            continue
        olds = []
        for o in alive:
            if (o.id == n.id or o.kind != "fact" or o.id in merged_away or o.created >= n.created
                    or o.pact_state == "open"):
                continue
            shared_tag = bool(set(n.tags) & set(o.tags))
            sim = overlap(n.text.translate(_NUMERALS), o.text.translate(_NUMERALS))
            if shared_tag or sim > 0:
                olds.append(((shared_tag, sim), o))
        if olds:
            olds.sort(key=lambda s: s[0], reverse=True)
            groups.append((n, [o for _, o in olds[:MAX_CANDIDATES]]))
    return groups[:MAX_PAIRS]


def _change_groups(new: list[Memory], alive: list[Memory],
                   merged_away: set[int]) -> list[tuple[Memory, list[Memory]]]:
    """Each new event of his with the older facts it might make untrue (memory v3 §11 item 7,
    approved 10-28): "他说又喝回原来那个了" was kept as a fading event while the fact on her
    card still said he had switched. Same candidates as `_update_groups`, from events."""
    groups = []
    for n in new:
        if n.kind != "event" or n.id in merged_away or n.text.lstrip().startswith("我"):
            continue
        olds = []
        for o in alive:
            if (o.kind != "fact" or o.id in merged_away or o.created >= n.created
                    or o.pact_state == "open"):
                continue
            shared_tag = bool(set(n.tags) & set(o.tags))
            sim = overlap(n.text.translate(_NUMERALS), o.text.translate(_NUMERALS))
            if shared_tag or sim > 0:
                olds.append(((shared_tag, sim), o))
        if olds:
            olds.sort(key=lambda s: s[0], reverse=True)
            groups.append((n, [o for _, o in olds[:MAX_CANDIDATES]]))
    return groups[:MAX_PAIRS]


def close_trailing_chat(night: Night) -> None:
    """1. a chat that trailed off without being closed"""
    stale = night.episodes.stale(night.now)
    if stale is not None and night.brain is not None:
        night.brain.close_episode(stale, night.now)
        night.report["closed"] = stale.id


def take_stock(night: Night) -> None:
    """Today's notes; and every note the pact words caught today (memory v3 §B2 D1/D2), to be read over."""
    store, day = night.store, night.day
    night.new = _new_today(store, day)
    caught = [m.id for m in store.alive() if m.pact and (m in night.new or m.last_time == day.isoformat())]
    if caught:
        night.report["pacts"] = caught


def merge_duplicates(night: Night) -> None:
    """2. duplicates -> one stronger memory"""
    if not night.thinker:
        return
    store = night.store
    for m in night.thinker.merge_pairs(_merge_pairs(night.new, store.alive())):
        if all(store.get(i).alive for i in m.ids):
            store.merge(list(m.ids), m.text, now=night.now)
            night.merged_away.update(m.ids)
    night.report["merged"] = len(night.merged_away) // 2


def replace_old_facts(night: Night) -> None:
    """3. a new fact that replaces an old one; 3a. a new event of his that makes an old fact
    untrue: the fact is rewritten as it is now"""
    if not night.thinker:
        return
    store = night.store
    updates = night.thinker.find_updates(_update_groups(night.new, store.alive(), night.merged_away))
    done = 0
    for u in updates:
        if store.get(u.old_id).alive and store.get(u.new_id).alive:
            store.supersede(u.old_id, u.new_id, why="update")
            done += 1
    night.report["updated"] = done
    rewritten = 0
    for old_id, text in night.thinker.rewrite_facts(_change_groups(night.new, store.alive(), night.merged_away)):
        if store.get(old_id).alive:
            store.correct(old_id, text, now=night.now)
            rewritten += 1
    night.report["rewritten"] = rewritten


def gist_repeats(night: Night) -> None:
    """3b. things that kept happening -> one gist each, without one-off details (decision 20)"""
    if not night.thinker:
        return
    repeated = night.store.gists_due()
    if repeated:
        rewritten = night.thinker.gists(repeated)
        for memory_id, text in rewritten.items():
            night.store.rewrite_as_gist(memory_id, text)
        night.report["gists"] = len(rewritten)

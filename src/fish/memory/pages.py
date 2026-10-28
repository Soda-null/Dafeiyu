"""Turning back to old chats (memory v3 step 8, §B3; waiting for the user's approval,
docs/memory_v3_zh.md §11 item 1).

What was never written down as a note can still be in the summary of the chat it was said in:
the name of the film, the score he got. When his line names a time ("昨晚", "上周五") or asks
her to remember ("记得", "叫啥", "咋样"), she may look at up to PAGES_SHOWN of those summaries,
each cut to PAGE_CHARS. Most turns do neither, and then nothing is looked at.

What she sees of a chat is what its level of forgetting left: the summary for the first
GIST_ONLY_AFTER_DAYS days, after that only the one-line gist unless it mattered (the rule
episodes.compress follows at night). A page is found by the words it shares with his line,
by its `keys` (the tags and names of the notes the chat left), and by its day when his line
names one; how he asks and the days he names are not what he asks about, and among the chats of
those days the ones sharing a character of it come first. What she could not answer back then
("我没记住，他好像没跟我说过") is left out of a page: it holds his old question, not the answer.
Never the messages themselves: a secret he typed, or a page he pasted, would come
back as "what he said". Each page is scrubbed again on the way out (scrub.redact) and is shown
as a summary, not his words (brain/prompt.py). No model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from fish.memory.episodes import GIST_ONLY_AFTER_DAYS, GIST_ONLY_BELOW_IMPORTANCE, Episode
from fish.memory.longterm import Memory, days_between, iso
from fish.memory.retrieval import FILLER
from fish.memory.scrub import redact, secret
from fish.memory.when import TIME_WORDS, time_hit, window

# His line asks her to remember something. With the days gone by he names, 15% of 小周's lines
# open the gate; on half of those no page is close enough and nothing is shown.
ASKS_MEMORY = re.compile(r"记得|还记|啥来着|叫啥|叫什么|是啥|干嘛了|咋样|多少|哪天|什么时候|几号|哪[个家部栋]")
# How he asks, not what about: also a quiz ("考考你", "他考我记不记得") is no exam.
HOW_ASKED = re.compile(rf"记不记得|还?记得[不吗没]|{ASKS_MEMORY.pattern}|来着|考考你|考你|考我")
# She could not answer: every such sentence on 小周's and the review databases' chats, none else.
MISSED = re.compile(r"没记住|没记得|答不上|没答上|没接住|想不起|记不清|(?:我|鱼|我说|哪[门个天样])忘了"
                    r"|没跟我说过|没告诉过?我|说过没有")
PAGES_SHOWN = 2
PAGE_CHARS = 160
# Below this a page shares a word or two with his line by chance. A day or a week he names is
# enough alone (when.SPAN_HIT 0.6, 0.45); a month needs a word too. On 小周 a page is shown on
# 7% of his lines (11% at 0.15); 0.15 to 0.4 bring back the same answers there, so a strict one.
PAGE_MIN = 0.3
KEYS_KEPT = 24
NAMED = re.compile(r"《([^》]{1,20})》")
SENTENCE = re.compile(r"(?<=[。！？!?；;\n])")
BARE_WEEKDAY = re.compile(r"(?<![上这本下])(?:周|星期|礼拜)[一二三四五六日天]")
NOT_WORD = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]+")
PRONOUNS = set("我你他她")


@dataclass(frozen=True)
class Page:
    episode: int
    day: date  # the day the chat was
    text: str  # scrubbed and cut, never the messages
    gist_only: bool  # only the one-line gist is left of it
    score: float


def _past(line: str, now: datetime) -> tuple[date, date] | None:
    """The days his line names, when they are all over: "昨晚", "上周五", "一月份"; not "今天"
    or "这周", which he says about what is going on, not to think back. A bare "周六" is not
    counted here: said without asking it is mostly the coming one ("周六去看演唱会") or today."""
    span = window(BARE_WEEKDAY.sub(" ", line), now)
    return span if span and span[1] < now.date() else None


def opens(line: str, now: datetime) -> bool:
    """Whether his line is one that makes a person think back: it asks, or names days gone by."""
    return bool(ASKS_MEMORY.search(line) or _past(line, now))


def keys_of(memories: list[Memory]) -> list[str]:
    """What a chat's notes are about, to find the chat by: their tags and the names in 《》."""
    out: list[str] = []
    for m in memories:
        for k in (*m.tags, *NAMED.findall(m.text)):
            k = k.strip()
            if len(k) >= 2 and k not in out and not secret(k):
                out.append(k)
    return out[:KEYS_KEPT]


def visible(ep: Episode, now: datetime) -> tuple[str, bool]:
    """What is left of a chat to look at now, and whether that is only its gist."""
    aged = ep.level >= 2 or (days_between(ep.ended, now) > GIST_ONLY_AFTER_DAYS
                             and (ep.importance or 0) < GIST_ONLY_BELOW_IMPORTANCE)
    return redact(ep.gist if aged else (ep.summary or ep.gist)), aged


def asked_about(cue: str) -> str:
    """What his line asks about: without how he asks and the days he names. "我上周考的啥来着"
    asks about an exam, and "上周" is in every summary that retells an older chat."""
    return TIME_WORDS.sub(" ", HOW_ASKED.sub(" ", cue))


def answered(text: str) -> str:
    """A page without the sentences where she could not answer. They hold his old question, so
    they match the next time he asks it, and show her only that she did not know (§B5: she
    does not tell him "你没跟我说过")."""
    return "".join(s for s in SENTENCE.split(text) if not MISSED.search(s)).strip()


def _chars(text: str) -> set[str]:
    return {c for c in NOT_WORD.sub("", text) if c not in FILLER and c not in PRONOUNS}


def _bigrams(text: str) -> set[str]:
    """Character pairs within each stretch of words, particles left out ("我吃的啥" -> 我吃, 吃啥)."""
    out = set()
    for part in NOT_WORD.split(text):
        chars = [c for c in part if c not in FILLER]
        out.update(a + b for a, b in zip(chars, chars[1:]))
    return out


def relevance(cue: str, text: str, keys: tuple[str, ...] | list[str]) -> float:
    """How much of his line the page holds: the share of his line's word pairs found in what is
    left of the chat or in its keys. How he asks ("记得吗", "咋样") and the days he names are not
    what he asks about, so they are left out of his line (asked_about); particles are dropped,
    so a key like "吃的" is no word pair at all and every chat about food does not match "我吃的啥"."""
    a = _bigrams(asked_about(cue))
    if not a:
        return 0.0
    index = _bigrams(text).union(*(_bigrams(k) for k in keys))
    return len(a & index) / len(a)


def shared_chars(cue: str, text: str, keys: tuple[str, ...] | list[str]) -> tuple[int, int]:
    """The characters of what he asks about found in the chat's keys, and in what is left of it
    (a quiz on her is not counted). Only to order chats that score the same: "我上周考的啥来着"
    leaves the one character 考, no word pair, and all of last week's chats score the same."""
    a = _chars(asked_about(cue))
    return len(a & _chars("".join(keys))), len(a & _chars(HOW_ASKED.sub(" ", text)))


def cut(text: str, cue: str, limit: int = PAGE_CHARS) -> str:
    """At most `limit` characters: whole sentences, the ones that share most with his line
    first, put back in their order."""
    if len(text) <= limit:
        return text
    parts = [s for s in SENTENCE.split(text) if s.strip()]
    a = _bigrams(asked_about(cue))
    order = sorted(range(len(parts)), key=lambda i: (-len(a & _bigrams(parts[i])), i))
    kept, used = set(), 0
    for i in order:
        if used + len(parts[i]) <= limit:
            kept.add(i)
            used += len(parts[i])
    if not kept:
        return text[:limit - 1] + "…"
    return "".join(parts[i] for i in sorted(kept)).strip()


def days_of(ep: Episode) -> set[date]:
    return {datetime.fromisoformat(ep.started).date(), datetime.fromisoformat(ep.last_active).date()}


def turn_back(episodes: list[Episode], line: str, now: datetime, *, cue: str | None = None,
              skip: set[int] | frozenset[int] = frozenset(), k: int = PAGES_SHOWN) -> list[Page]:
    """The pages his line makes her look at, best first; [] when it is not a line that makes
    one think back. line: his line (the gate, and the days it names); cue: what to search with
    (default his line). skip: chats not to look at (the one going on now). When his line only
    names days and does not ask ("昨晚吃了麻辣烫，辣死"), only chats from those days."""
    asks = bool(ASKS_MEMORY.search(line))
    span = window(line, now) if asks else _past(line, now)
    if not asks and span is None:
        return []
    cue = cue or line
    stamp = iso(now)
    rows = []
    for ep in episodes:
        if ep.id in skip or ep.ended is None or ep.ended > stamp:
            continue
        text, aged = visible(ep, now)
        text = answered(text)
        if not text:
            continue
        rel = relevance(cue, text, ep.keys)
        if span and any(span[0] <= d <= span[1] for d in days_of(ep)):
            rel += time_hit((span[1] - span[0]).days + 1) * (1 - rel)
        elif not asks:
            continue
        if rel >= PAGE_MIN:
            rows.append((rel, shared_chars(cue, text, ep.keys), ep.ended, ep, text, aged))
    rows.sort(key=lambda r: r[:3], reverse=True)
    return [Page(ep.id, datetime.fromisoformat(ep.started).date(), cut(text, cue), aged, rel)
            for rel, _, _, ep, text, aged in rows[:k]]

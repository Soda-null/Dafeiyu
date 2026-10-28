"""Long-term memories: the `memories` table and a memory's lifecycle.

add -> (recall) touch -> correct (supersede) / merge -> never deleted.
Data and math only; the text of a memory is written by the brain or the nightly routine.
Field meanings: docs/memory_design_zh.md §4.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from fish.memory import pacts as pk
from fish.memory import stability as st
from fish.memory.scrub import secret
from fish.memory.patterns import day_of as her_day
from fish.memory.when import absolute, agree_with_line, day_of, fix_weekday, written_day

KINDS = ("fact", "event", "howto", "insight", "self", "world")  # world: things she saw online
PROFILE_IMPORTANCE = 8  # facts at or above this importance form the always-present profile
PROFILE_SIZE = 12
# Card facts that keep him safe come right after the pinned ones (memory v3 §B3).
SAFETY = re.compile(r"过敏|不耐(?!烦)|病|药")
# A card fact about someone around him: one that starts with another name ("大壮是他表哥……",
# "团子是只仓鼠"), or with his family, friends or people at work ("他表哥……", "他合租的室友叫……").
# They go on the card after the facts about him himself, so many friends never push his school or
# his home off it. Kinship and social words of the language, not of any one friend's story.
RELATIONS = ("爸|妈|父亲|母亲|爷爷|奶奶|姥姥|姥爷|外公|外婆|祖|[表堂]?[哥姐弟妹]|兄|叔|伯|姨|舅|姑|侄|甥"
             "|儿子|女儿|孩子|老婆|老公|媳妇|对象|男朋友|女朋友|前任|室友|舍友|同学|同事|朋友|闺蜜|发小"
             "|老师|导师|老板|领导|上司|组长|经理|师兄|师姐|师弟|师妹|邻居|房东")
ABOUT_OTHERS = re.compile(rf"^(?![他她])|^[他她](?:[^，。,；;的]{{0,4}}的)?(?:{RELATIONS})")

# Choosing before writing (decision 19): what `note` refuses or folds into an old memory.
REPEAT_SIMILARITY = 0.5  # same kind, this much bigram overlap (dates removed): a repeat
FACT_REPEAT_SIMILARITY = 0.8  # facts differ by one number when he corrects himself; stricter
# Her own life (memory v3 step 7, §B4, waiting for the user's approval: docs/memory_v3_zh.md §11):
# she tells the same thread in new words each night ("数米粒" 27 ways in a year), so a looser bar,
# and no more than KIND_CAPS["self"] of them alive.
SELF_REPEAT_SIMILARITY = 0.35
KIND_CAPS = {"insight": 20, "howto": 20, "self": 30}  # beyond this the least stable is pushed out
# Notes about the chat itself (he is testing her memory, she could not recall) are not things about
# him: "他欠我一样东西，具体是什么我记不清了" would later read as a debt she knows of.
ABOUT_THE_CHAT = re.compile(r"考我|考她|记性|记不记得|试探我|试探她|测我记|我(?:记不清|想不起|没记住)")
ABOUT_HIM_KINDS = ("fact", "event", "insight", "howto")
GIST_AT = (3, 6, 12, 24, 48, 96)  # times at which a repeated thing is rewritten as a gist
# Only for things that happen (his events, her own doings). A fact, a rule or an insight said again
# is the same thing confirmed, not something that happened again: counted, never "好几回".
HAPPENING_KINDS = ("event", "self")
# Insights and howto rules start unconfirmed (decision 21): they need evidence on this many
# different days before they get the strength of a fact about him.
RULE_KINDS = ("insight", "howto")
EVIDENCE_DAYS = 3
UNCONFIRMED = "待印证"
# Words that make a "him himself" note a passing state (a sore throat last week), not who he is.
FOR_NOW = re.compile(r"最近|这几天|这阵子|这周|上周|今天|昨天|刚才|还没好|这次|暂时|目前|这两天")
# ... unless it names something that lasts (memory v3 §B2 D3): "他说妹妹今天打电话来，她叫小雨"
# is his sister, not today's news; "以后提醒他" is a standing thing.
LASTING = re.compile(r"妹|弟|哥|姐|爸|妈|家在|老家|过敏|不耐|不能吃|专业|学校|年级|公司|岗位|生日|最爱"
                     r"|外号|从小|以后")
# A repeat that brings a number or a title the old memory lacks is news, not a repeat (§B2 D4).
_DETAIL = re.compile(r"\d+|《[^》]+》")
_DATE = re.compile(r"\d{4}\s*[-年/.]\s*\d{1,2}\s*[-月/.]\s*\d{1,2}\s*日?")
# Why a memory stopped being current (memory v3). Only a correction he made and an update the
# night found are "what she used to think"; a memory merged away or pushed out by a cap is not.
WHYS = ("correct", "update", "merge", "cap", "expired")
SHOWN_AS_FORMER = ("correct", "update")
SETTLED = {"kept": "兑现了", "dropped": "后来说不算了"}  # how a settled pact reads
PACT_LINK = 0.3  # overlap at which a follow-up is about an open promise (memory v3 §B1)
SOURCE_LINK = 0.3  # overlap at which a follow-up is about a note from the same chat (§B1)
# Things that end in a result she will want to hear (memory v3 §B2): an exam, an interview, a move.
# 考虑 is thinking it over, not an exam.
OUTCOME_WORDS = re.compile(r"考(?!虑)|面试|述职|答辩|演示|汇报|比赛|体检|复查|看病|看房|搬家|录取|申请|结题|评审")
OUTCOME_DAYS = 30  # how far back an event can still get its result at the close
OUTCOMES_SHOWN = 3
# The follow-ups she let go were written as events before memory v3 step 1; they fade within
# weeks (stability.UNASKED_MAX_DAYS), whoever the merge made the subject. Only that row shape
# ("我/他一直没问成他……"): his own "他一直没问成导师……" is an ordinary thing about him.
UNASKED = re.compile(r"^[我他]一直没问成他")
# A note is about what he said, not what she said (memory v3 §14): her guess at a question of his,
# or a turn of his she made up, written down as his, is a false memory for good. Its content words
# (no dates, no function words, no persons) must not come from her lines of the chat alone.
ECHO_HIS = 0.2  # less than this share of the note's words from his lines ...
ECHO_HERS = 0.5  # ... and this much from words only she said: hers, not his
_NOT_CONTENT = re.compile(r"[的了是在和就也都还又很吧呢啊吗呀哦嗯他她我你]")
_DAY_WORDS = re.compile(r"\d{4}\s*[-年/.]\s*\d{1,2}(?:\s*[-月/.]\s*\d{1,2}\s*[日号]?)?|\d{1,2}\s*月(?:\s*\d{1,2}\s*[日号])?"
                        r"|\d{1,2}\s*[日号点时]|(?:周|星期|礼拜)[一二三四五六日天]")


def strongest_about(abouts: list[str | None]) -> str | None:
    """What a merged memory is about: the strongest of its sources (一辈子 > 本人 > 日常 > 路过).
    It stays unconfirmed only when every source was; a merge is not evidence."""
    known = [a for a in abouts if a in st.ABOUTS]
    if known:
        return max(known, key=st.ABOUTS.index)
    return UNCONFIRMED if abouts and all(a == UNCONFIRMED for a in abouts) else None


def _bigrams(text: str) -> set[str]:
    chars = [c for c in _DATE.sub("", text) if c.isalnum()]
    return {a + b for a, b in zip(chars, chars[1:])}


def overlap(a: str, b: str) -> float:
    """Dice overlap of character bigrams with dates taken out: "he had lab on 10-26" and
    "he had lab on 10-27" are the same words."""
    x, y = _bigrams(a), _bigrams(b)
    return 2 * len(x & y) / (len(x) + len(y)) if x and y else 0.0


def content_words(text: str) -> set[str]:
    """The two-character runs of what a line is about: no dates, no function words, no persons."""
    chars = [c for c in _NOT_CONTENT.sub("", _DAY_WORDS.sub(" ", text)) if c.isalnum() or c == " "]
    return {a + b for a, b in zip(chars, chars[1:]) if a != " " and b != " "}


# A number said in words ("两千八", "十五个") is the number she writes in digits ("2800"). Two or more
# numeral characters, or one before a unit; "一下", "一起" are no numbers.
_CN_NUMBER = re.compile(r"[一二两三四五六七八九十][零一二两三四五六七八九十百千万]+"
                        r"|[一二两三四五六七八九十](?=[块元岁斤只个本次])")
_CN_DIGIT = {c: i for i, c in enumerate("零一二三四五六七八九")} | {"两": 2}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000}


def cn_number(word: str) -> int:
    """"两千八" -> 2800, "一万二" -> 12000, "三百零五" -> 305, "十五" -> 15, "二零二七" -> 2027."""
    if not any(c in _CN_UNIT or c == "万" for c in word):
        return int("".join(str(_CN_DIGIT[c]) for c in word))
    total = section = digit = 0
    last, prev = 1, ""
    for c in word:
        if c in _CN_DIGIT:
            digit = _CN_DIGIT[c]
        elif c in _CN_UNIT:
            section += (digit or (1 if c == "十" else 0)) * _CN_UNIT[c]
            digit, last = 0, _CN_UNIT[c]
        else:  # 万
            total += (section + digit) * 10000
            section = digit = 0
            last = 10000
        prev = c
    if digit and last >= 100 and prev != "零" and word[-2] in "百千万":
        digit *= last // 10  # "两千八": the unit after the last one is left out
    return total + section + digit


def digits(text: str) -> str:
    """The numbers of a line in digits: "一个月两千八" -> "一个月2800"."""
    return _CN_NUMBER.sub(lambda m: str(cn_number(m.group(0))), text)


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+", _DAY_WORDS.sub(" ", text)))


def echoes_her(text: str, his: str, hers: str) -> bool:
    """The note says what she said in the chat (`hers`, her lines), not what he said (`his`):
    hardly any of its words are his and most are hers alone, or it has a number only she said
    ("两千八" he said is her "2800")."""
    text, his, hers = digits(text), digits(his), digits(hers)
    note = content_words(text)
    if note:
        him = content_words(his)
        only_hers = content_words(hers) - him
        if len(note & him) < ECHO_HIS * len(note) and len(note & only_hers) >= ECHO_HERS * len(note):
            return True
    return bool(_numbers(text) & (_numbers(hers) - _numbers(his)))


def iso(now: datetime) -> str:
    return now.isoformat(timespec="seconds")


def days_between(earlier: str, now: datetime) -> float:
    return (now - datetime.fromisoformat(earlier)).total_seconds() / 86400


@dataclass(frozen=True)
class Memory:
    id: int
    kind: str
    text: str
    created: str
    source_episode: int | None
    importance: int
    valence: float
    arousal: float
    stability: float
    last_recalled: str
    recall_count: int
    superseded_by: int | None
    merged_from: tuple[int, ...]
    tags: tuple[str, ...]
    pinned: bool
    source: str | None = None  # kind=world: where she saw it
    times: int = 1  # how many times it happened or was said (decision 20)
    gist_due: bool = False  # often enough now to be rewritten as a gist tonight
    pattern: str | None = None  # how one time of it was worded, kept when the text became a gist
    about: str | None = None  # 路过 / 日常 / 本人 / 一辈子, or 待印证 for a rule not yet confirmed
    last_time: str | None = None  # YYYY-MM-DD it last happened; a day counts once
    why: str | None = None  # why it was superseded (WHYS); None while current, or before v3
    happened_on: str | None = None  # YYYY-MM-DD it happened (or will); None before v3
    pact: str | None = None  # a promise between them or his nickname for her: pacts.WHO
    pact_state: str | None = None  # open / kept / dropped; None for the nickname
    outcome: str | None = None  # how it turned out, with the day he said so; the text never changes

    @property
    def unconfirmed(self) -> bool:
        return self.about == UNCONFIRMED

    @property
    def often(self) -> str:
        """How she feels about how often: nothing, 好几回, 很多回 (only for things that happen)."""
        if self.kind not in HAPPENING_KINDS or self.times < 2:
            return ""
        return "好几回了" if self.times < 5 else "很多回了"

    def line(self) -> str:
        """The text as it goes into a prompt: with "（很多回了）" when it kept happening,
        "（还说不准）" for a rule she has not seen confirmed yet, and "→结果：……" once he told her
        how it went."""
        if self.unconfirmed:
            return f"{self.text}（还说不准）"
        if self.pact_state in SETTLED:
            return f"{self.text}（{SETTLED[self.pact_state]}）"
        text = f"{self.text}（{self.often}）" if self.often else self.text
        return f"{text} →结果：{self.outcome}" if self.outcome else text

    def retrievability(self, now: datetime) -> float:
        """A fact about him himself never falls below HIMSELF_R_FLOOR (memory v3 §B4): she may
        be unsure of his hometown after a year, she does not lose it."""
        floor = st.HIMSELF_R_FLOOR if self.kind == "fact" and self.about == "本人" else 0.0
        return st.retrievability(self.stability, days_between(self.last_recalled, now), floor)

    @property
    def ceiling(self) -> float:
        """The most S it can get from recall, a merge or a correction (memory v3 §B4)."""
        return ceiling_of(self.kind, self.text, self.about)

    def fuzzy(self, now: datetime) -> bool:
        return self.retrievability(now) < st.FUZZY_R

    @property
    def alive(self) -> bool:
        return self.superseded_by is None


def about_of(kind: str, about: str | None) -> str | None:
    """路过 is a meal, what he is doing now, today's plan: things that happen. A lasting fact
    filed there ("his friend's cat is called X") counts as 日常, wherever it is read: when it is
    written, when its ceiling is worked out, when it is corrected or merged, when a database
    written before this rule is migrated."""
    return "日常" if kind == "fact" and about == "路过" else about


def ceiling_of(kind: str, text: str, about: str | None) -> float:
    return st.ceiling(about_of(kind, about), unasked=kind == "event" and bool(UNASKED.search(text)))


def capped(stability: float, ceiling: float, was: float = 0.0) -> float:
    """stability, no higher than the ceiling; a memory already above it (written before memory
    v3) does not grow, and is not cut either: lowering what is there is the migration's job."""
    return min(stability, max(was, ceiling))


def card_order(m: Memory) -> tuple:
    """Sort key of her card: pinned, then safety, then facts about him himself before facts
    about people around him, each by the latest day it came up."""
    last = date.fromisoformat(m.last_time or m.created[:10])
    return (not m.pinned, not SAFETY.search(m.text), bool(ABOUT_OTHERS.search(m.text.lstrip())),
            -last.toordinal(), -m.importance, m.id)


def _from_row(r: sqlite3.Row) -> Memory:
    return Memory(
        id=r["id"], kind=r["kind"], text=r["text"], created=r["created"],
        source_episode=r["source_episode"], importance=r["importance"],
        valence=r["valence"], arousal=r["arousal"], stability=r["stability"],
        last_recalled=r["last_recalled"], recall_count=r["recall_count"],
        superseded_by=r["superseded_by"],
        merged_from=tuple(json.loads(r["merged_from"] or "[]")),
        tags=tuple(json.loads(r["tags"] or "[]")),
        pinned=bool(r["pinned"]),
        source=r["source"] if "source" in r.keys() else None,
        times=r["times"] if "times" in r.keys() else 1,
        gist_due=bool(r["gist_due"]) if "gist_due" in r.keys() else False,
        pattern=r["pattern"] if "pattern" in r.keys() else None,
        about=r["about"] if "about" in r.keys() else None,
        last_time=r["last_time"] if "last_time" in r.keys() else None,
        why=r["why"] if "why" in r.keys() else None,
        happened_on=r["happened_on"] if "happened_on" in r.keys() else None,
        pact=r["pact"] if "pact" in r.keys() else None,
        pact_state=r["pact_state"] if "pact_state" in r.keys() else None,
        outcome=r["outcome"] if "outcome" in r.keys() else None,
    )


def why_before_v3(old: Memory, new: Memory) -> str:
    """A memory superseded before the `why` column existed: guessed the way the v3 migration
    writes it (docs/memory_v3_zh.md §8, scripts/migrate_v3.py). A source of a merge was merged;
    a rule replaced by another rule, not merged, was pushed out by the cap; anything else was
    an update."""
    if old.id in new.merged_from:
        return "merge"
    if old.kind in RULE_KINDS and new.kind == old.kind:
        return "cap"
    return "update"


class MemoryStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # --- write -------------------------------------------------------------

    def add(
        self,
        kind: str,
        text: str,
        *,
        importance: int,
        valence: float = 0.0,
        arousal: float = 0.0,
        source_episode: int | None = None,
        tags: tuple[str, ...] | list[str] = (),
        pinned: bool = False,
        stability: float | None = None,
        merged_from: tuple[int, ...] | list[int] = (),
        source: str | None = None,
        now: datetime | None = None,
        happened_on: str | None = None,
    ) -> Memory:
        """happened_on: the day it happened; by default the one day its text names, else today."""
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
        now = now or datetime.now()
        importance = st.clamp_importance(importance)
        pinned = pinned or importance >= st.PINNED_IMPORTANCE
        if stability is None:
            stability = st.initial_stability(importance, valence)
        if pinned:
            stability = st.INFINITE
        happened_on = happened_on or (day_of(text, now) or now.date()).isoformat()
        cur = self.conn.execute(
            "INSERT INTO memories (kind, text, created, source_episode, importance, valence, arousal,"
            " stability, last_recalled, recall_count, superseded_by, merged_from, tags, pinned, source,"
            " happened_on) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, ?, ?, ?)",
            (kind, text, iso(now), source_episode, importance, valence, arousal, stability,
             iso(now), json.dumps(list(merged_from)), json.dumps(list(tags), ensure_ascii=False),
             int(pinned), source, happened_on),
        )
        self.conn.commit()
        return self.get(cur.lastrowid)

    def note(self, kind: str, text: str, *, importance: int, now: datetime | None = None,
             said: str = "", heard: str | None = None, **fields) -> Memory | None:
        """How the brain and the routines write (decision 19): choose before writing.

        None: not written (it is about the chat itself, not about him). An older memory:
        this was a repeat, so the old one was recalled instead. Otherwise the new memory;
        if its kind is over its cap, the least stable one of that kind is pushed out.
        said: his line the note came from; for an event, its time words date the note when the
        note's own text names no day (memory v3 §B1). A date that disagrees with the weekday written
        next to it is moved to that weekday first (§B2 D5); a written-out date a few days off the one
        day his line names ("大后天" counted wrong) becomes that day (§14.3, when.agree_with_line).
        heard: "chat" or "close" when the note comes from talking with him; only such a note can
        be a promise between them or his nickname for her (§B2 D1/D2, pacts.py).
        A note that holds a secret (a code, a password) is never written, whoever asks (scrub.py)."""
        now = now or datetime.now()
        if secret(text):
            return None
        text = fix_weekday(text, now.date())
        if said and heard in pk.HEARD:  # "大后天" counted by the model as 05-08 is 05-07 (§14.3)
            text = agree_with_line(text, said, her_day(now), told=now.date())
        if kind in ABOUT_HIM_KINDS and ABOUT_THE_CHAT.search(text):
            return None
        said_as = text  # the words as said, for the day they name (two days named: no one day)
        if heard in pk.HEARD:
            text = absolute(text, now)  # "下个月19号" read next month is not May (§14)
        about = fields.pop("about", None)
        pact = state = None
        if heard in pk.HEARD and kind in RULE_KINDS and pk.ruled_promise(text):
            kind = "fact"  # "他答应我，……" filed as an insight: a rule would fade in weeks
        if heard in pk.HEARD:
            if pk.nickname(text):
                kind, about, pact = "fact", "一辈子", "both"  # what he calls her is a fact for life
            elif (pact := pk.promise(text, kind)) is not None:
                about, state = "一辈子", "open"  # however much it sounds like a plan
        if kind == "self" and text.lstrip().startswith(("他", "她")):
            return None  # her life threads are about her; his things are noted in chat
        # (the persona calls him 他 or 她, FISH_OWNER; she is never the subject in third person)
        if about == "本人" and FOR_NOW.search(text) and not LASTING.search(text):
            about = "日常"  # a state for now is not who he is; it does not go on his card
        about = about_of(kind, about)  # a fact is never 路过: it would sit under the 14-day ceiling
        same = self.repeat_of(kind, text, now, lifelong=about == "一辈子")
        if same is not None and not self.adds_detail(text, same):
            again = self.happened_again(same.id, now)
            return self.raise_to(again, about, fields.get("arousal", 0.0), pact, state)
        if kind in RULE_KINDS:
            about = UNCONFIRMED  # however sure the model sounds, one day is one day
            fields["stability"] = st.UNCONFIRMED_DAYS
        elif about in st.ABOUTS:
            fields["stability"] = st.stability_from(about, fields.get("arousal", 0.0))
            fields["pinned"] = about == "一辈子"
        if "stability" in fields:
            importance = st.importance_of(fields["stability"])
        said = said if kind == "event" else ""  # a lasting fact is not dated by "明天" in his line
        fields.setdefault("happened_on", (day_of(said_as, now, said) or now.date()).isoformat())
        new = self.add(kind, text, importance=importance, now=now, **fields)
        self.conn.execute("UPDATE memories SET about = ?, last_time = ?, pact = ?, pact_state = ? WHERE id = ?",
                          (about, iso(now)[:10], pact, state, new.id))
        self.conn.commit()
        new = self.get(new.id)
        cap = KIND_CAPS.get(kind)
        if cap is not None:
            others = [m for m in self.alive(kind) if m.id != new.id and not m.pinned]
            for weakest in sorted(others, key=lambda m: (m.stability, m.id))[:max(0, len(others) + 1 - cap)]:
                self.supersede(weakest.id, new.id, why="cap")
        return new

    def repeat_of(self, kind: str, text: str, now: datetime, *, lifelong: bool = False) -> Memory | None:
        """The live memory this text repeats, if any. Across days too (decision 20): the
        same thing every Friday is one memory that happened many times. A lifelong fact (his
        birthday) said in other words is still the same one: against pinned facts the bar
        is the ordinary one, not the strict one for facts."""
        threshold = {"fact": FACT_REPEAT_SIMILARITY, "self": SELF_REPEAT_SIMILARITY}.get(kind, REPEAT_SIMILARITY)
        best: tuple[float, Memory] | None = None
        for m in self.alive(kind):
            sim = max(overlap(text, m.text), overlap(text, m.pattern) if m.pattern else 0.0)
            if lifelong and m.pinned and sim >= REPEAT_SIMILARITY:
                sim = max(sim, threshold)
            if sim >= threshold and (best is None or sim > best[0]):
                best = (sim, m)
        return best[1] if best else None

    @staticmethod
    def adds_detail(text: str, old: Memory) -> bool:
        """The new words bring a number or a 《title》 the old memory does not have ("他考了82分"
        after "他考完期中了"): that is news, written as a memory of its own (memory v3 §B2 D4)."""
        known = set(_DETAIL.findall(_DATE.sub("", old.text + " " + (old.pattern or ""))))
        return any(d not in known for d in _DETAIL.findall(_DATE.sub("", text)))

    def raise_to(self, m: Memory, about: str | None, arousal: float = 0.0,
                 pact: str | None = None, state: str | None = None) -> Memory:
        """A repeat that says more of it than the old memory did (memory v3 §B2 D4): the promise
        first filed as 日常, told again as a promise. The old memory rises to the new about, with
        its strength and pin, and becomes the pact; never down. Rules keep their own evidence."""
        if m.kind in RULE_KINDS:
            return m
        rank = {a: i for i, a in enumerate(st.ABOUTS)}
        sets: dict[str, object] = {}
        if about in rank and rank[about] > rank.get(m.about, -1):
            s = max(m.stability, st.stability_from(about, arousal))
            sets.update(about=about, stability=s, importance=max(m.importance, st.importance_of(s)),
                        pinned=int(m.pinned or about == "一辈子"))
        if pact and not m.pact:
            sets.update(pact=pact, pact_state=state)
        if sets:
            cols = ", ".join(f"{c} = ?" for c in sets)
            self.conn.execute(f"UPDATE memories SET {cols} WHERE id = ?", (*sets.values(), m.id))
            self.conn.commit()
        return self.get(m.id)

    def happened_again(self, memory_id: int, now: datetime | None = None) -> Memory:
        """The same thing once more: recalled once; on a new day, one more time, flagged for
        a gist rewrite at 3, 6, 12, ... A rule seen on its third day is confirmed: it gets the
        strength of a fact about him (decision 21)."""
        now = now or datetime.now()
        m = self.touch(memory_id, now)
        today = iso(now)[:10]
        if m.last_time == today:
            return m  # said twice the same day: still one time
        times = m.times + 1
        due = times in GIST_AT and m.kind in HAPPENING_KINDS
        self.conn.execute("UPDATE memories SET times = ?, gist_due = gist_due OR ?, last_time = ? WHERE id = ?",
                          (times, int(due), today, memory_id))
        if m.unconfirmed and times >= EVIDENCE_DAYS:
            s = max(m.stability, st.stability_from("本人", m.arousal))
            self.conn.execute("UPDATE memories SET about = '本人', stability = ?, importance = ? WHERE id = ?",
                              (s, st.importance_of(s), memory_id))
        self.conn.commit()
        return self.get(memory_id)

    def weaken(self, memory_id: int, now: datetime | None = None) -> Memory:
        """She sees a rule is no longer true: it fades within days instead of lasting."""
        now = now or datetime.now()
        self.conn.execute("UPDATE memories SET stability = MIN(stability, ?), last_recalled = ? WHERE id = ?",
                          (st.WEAKENED_DAYS, iso(now), memory_id))
        self.conn.commit()
        return self.get(memory_id)

    def gists_due(self) -> list[Memory]:
        rows = self.conn.execute("SELECT * FROM memories WHERE gist_due = 1 AND superseded_by IS NULL"
                                 " ORDER BY id")
        return [_from_row(r) for r in rows]

    def rewrite_as_gist(self, memory_id: int, text: str) -> Memory:
        """Nightly: the one-off details are gone, the gist stays; same memory, same strength."""
        self.conn.execute("UPDATE memories SET pattern = COALESCE(pattern, text), text = ?, gist_due = 0"
                          " WHERE id = ?", (text, memory_id))
        self.conn.commit()
        return self.get(memory_id)

    def touch(self, memory_id: int, now: datetime | None = None, *, strengthen: bool = True) -> Memory:
        """She just used this memory: it gets stronger, more so if it was nearly gone, up to its
        ceiling. strengthen=False: used, so fresh again, but no stronger (a fact on her card he
        just mentioned: it is in front of her every turn anyway, memory v3 §B4)."""
        now = now or datetime.now()
        m = self.get(memory_id)
        new_s = st.after_recall(m.stability, m.retrievability(now)) if strengthen else m.stability
        new_s = capped(new_s, m.ceiling, m.stability)
        self.conn.execute(
            "UPDATE memories SET stability = ?, last_recalled = ?, recall_count = recall_count + 1"
            " WHERE id = ?",
            (new_s, iso(now), memory_id),
        )
        self.conn.commit()
        return self.get(memory_id)

    def repoint(self, old_ids: list[int], new_id: int) -> None:
        """Follow-ups about a memory that was replaced are about the one that replaced it."""
        self.conn.execute(f"UPDATE prospective SET source_memory = ? WHERE source_memory IN"
                          f" ({', '.join('?' * len(old_ids))})", (new_id, *old_ids))
        self.conn.commit()

    def supersede(self, old_id: int, new_id: int, *, why: str) -> None:
        if why not in WHYS:
            raise ValueError(f"why must be one of {WHYS}, got {why!r}")
        self.conn.execute("UPDATE memories SET superseded_by = ?, why = ? WHERE id = ?",
                          (new_id, why, old_id))
        self.conn.commit()

    def correct(
        self, old_id: int, text: str, *, importance: int | None = None,
        now: datetime | None = None,
    ) -> Memory:
        """He corrected her: a new memory replaces the old one, which stays as 'what she used to think'.
        It keeps what the old one was about (his major corrected is still about him himself), its
        pact, its outcome, and the day it happened unless the new words name another one. New words
        that hold a secret change nothing: the old memory is returned as it was."""
        old = self.get(old_id)
        if secret(text):
            return old
        now = now or datetime.now()
        importance = old.importance if importance is None else importance
        fresh = st.initial_stability(importance, old.valence)
        stability = max(fresh, old.stability) if fresh != st.INFINITE else st.INFINITE
        stability = capped(stability, ceiling_of(old.kind, text, old.about), old.stability)
        new = self.add(
            old.kind, text, importance=importance, valence=old.valence, arousal=old.arousal,
            source_episode=old.source_episode, tags=old.tags, pinned=old.pinned,
            stability=stability, now=now,
            happened_on=(d.isoformat() if (d := day_of(text, now)) else old.happened_on),
        )
        self.conn.execute("UPDATE memories SET about = ?, last_time = ?, pact = ?, pact_state = ?, outcome = ?"
                          " WHERE id = ?", (about_of(old.kind, old.about), iso(now)[:10], old.pact,
                                            old.pact_state, old.outcome, new.id))
        self.supersede(old_id, new.id, why="correct")
        self.repoint([old_id], new.id)
        return self.get(new.id)

    def merge(self, ids: list[int], text: str, *, now: datetime | None = None) -> Memory:
        """Nightly: several near-duplicates become one, more stable (up to its ceiling), with its sources noted.
        What it is about, whether it is pinned, the pact (still open if any source was), the latest
        outcome and the day it last happened carry over; so does
        the day it happened (the latest of its sources), unless the merged words write a date."""
        olds = [self.get(i) for i in ids]
        if not olds:
            raise ValueError("merge needs at least one memory")
        now = now or datetime.now()
        # only a date written out in the merged words: their "明天" was said on its source's
        # day, and read at night it would land a day late
        latest = max(datetime.fromisoformat(o.created) for o in olds)
        tags: list[str] = []
        for o in olds:
            tags += [t for t in o.tags if t not in tags]
        about = about_of(olds[0].kind, strongest_about([o.about for o in olds]))
        strongest = max(o.stability for o in olds)
        new = self.add(
            olds[0].kind, text,
            importance=max(o.importance for o in olds),
            valence=sum(o.valence for o in olds) / len(olds),
            arousal=max(o.arousal for o in olds),
            source_episode=olds[0].source_episode, tags=tags,
            pinned=any(o.pinned for o in olds),
            stability=capped(st.after_merge(*(o.stability for o in olds)),
                             ceiling_of(olds[0].kind, text, about), strongest),
            merged_from=ids, now=now,
            happened_on=(d.isoformat() if (d := written_day(text, latest.date()))
                         else max((o.happened_on for o in olds if o.happened_on), default=None)),
        )
        for o in olds:
            self.supersede(o.id, new.id, why="merge")
        self.repoint(ids, new.id)
        times = sum(o.times for o in olds)  # both counts carry over (decision 20)
        last = max((o.last_time for o in olds if o.last_time), default=None)
        pact = next((o.pact for o in olds if o.pact), None)
        states = [o.pact_state for o in olds if o.pact_state]
        outcome = next((o.outcome for o in sorted(olds, key=lambda o: o.created, reverse=True) if o.outcome), None)
        self.conn.execute("UPDATE memories SET times = ?, about = ?, last_time = ?, pact = ?, pact_state = ?,"
                          " outcome = ? WHERE id = ?",
                          (times, about, last, pact,
                           "open" if "open" in states else next(iter(states), None), outcome, new.id))
        self.conn.commit()
        return self.get(new.id)

    # --- read --------------------------------------------------------------

    def get(self, memory_id: int) -> Memory:
        row = self.conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if row is None:
            raise KeyError(f"no memory {memory_id}")
        return _from_row(row)

    def alive(self, kind: str | None = None) -> list[Memory]:
        sql = "SELECT * FROM memories WHERE superseded_by IS NULL"
        args: tuple = ()
        if kind:
            sql += " AND kind = ?"
            args = (kind,)
        return [_from_row(r) for r in self.conn.execute(sql + " ORDER BY id", args)]

    def profile(self, limit: int = PROFILE_SIZE) -> list[Memory]:
        """The facts she always keeps in mind (her card): pinned first, then what keeps him
        safe (allergies, illness, medicine), then what is about him himself, then the people
        around him (ABOUT_OTHERS), each by when it last came up. Facts about
        him himself (about = 本人, decision 21) always qualify. Not by stability (memory v3
        §B3): how strongly she holds a fact says nothing about whether it is who he is now.
        His nickname is on it (a pact with no state); a promise is not, whatever its state: an
        open one has its own block (`pacts`), a settled one is pinned and comes back when
        recalled (§B3), so kept promises never crowd his allergy off the card."""
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE superseded_by IS NULL AND pact_state IS NULL"
            " AND ((kind = 'fact' AND (pinned = 1 OR importance >= ? OR about = '本人'))"
            "      OR (pact IS NOT NULL AND pinned = 1))", (PROFILE_IMPORTANCE,)
        )
        return sorted(map(_from_row, rows), key=card_order)[:limit]

    def pacts(self, limit: int = pk.PACTS_SHOWN, *, settled: bool = False) -> list[Memory]:
        """The promises between them still open, latest first (memory v3 §B3): always in front of
        her in a block of their own, so they leave her card. settled: he asks what was promised
        (pacts.asks_pact), so the ones kept or called off come after the open ones (§14)."""
        states = "('open', 'kept', 'dropped')" if settled else "('open')"
        rows = self.conn.execute(
            f"SELECT * FROM memories WHERE superseded_by IS NULL AND pact_state IN {states}"
            " ORDER BY pact_state = 'open' DESC, COALESCE(last_time, substr(created, 1, 10)) DESC, id DESC"
            " LIMIT ?", (limit,)
        )
        return [_from_row(r) for r in rows]

    def make_pact(self, memory_id: int, who: str) -> Memory:
        """His own line made a promise and the note of it was not taken for one (memory v3 §14):
        it becomes an open pact, pinned, for life; a rule or an insight becomes a fact."""
        if who not in pk.WHO:
            raise ValueError(f"who must be one of {pk.WHO}, got {who!r}")
        self.conn.execute(
            "UPDATE memories SET kind = CASE WHEN kind IN ('insight', 'howto') THEN 'fact' ELSE kind END,"
            " about = '一辈子', pinned = 1, stability = ?, importance = ?, pact = ?, pact_state = 'open'"
            " WHERE id = ?", (st.INFINITE, st.importance_of(st.INFINITE), who, memory_id))
        self.conn.commit()
        return self.get(memory_id)

    def pact_for(self, text: str) -> Memory | None:
        """The open promise a follow-up is about ("期末考完去海边了吗" and the promise of the
        sea): the one it overlaps most, at PACT_LINK or more. A shared tag alone is not enough:
        "问问他期末考得怎么样" says 期末 too, and a linked follow-up never runs out."""
        best = max(self.pacts(limit=-1), key=lambda p: overlap(text, p.text), default=None)
        return best if best is not None and overlap(text, best.text) >= PACT_LINK else None

    def settle(self, memory_id: int, state: str, now: datetime | None = None) -> Memory:
        """He kept a promise, or said it is off: it leaves the block. The memory stays pinned and
        its words stay as they were, read with "（兑现了）" when it is recalled; never on her card."""
        if state not in pk.STATES[1:]:
            raise ValueError(f"a pact is settled as kept or dropped, got {state!r}")
        now = now or datetime.now()
        self.conn.execute("UPDATE memories SET pact_state = ?, last_time = ? WHERE id = ?",
                          (state, iso(now)[:10], memory_id))
        self.conn.commit()
        return self.get(memory_id)

    def set_outcome(self, memory_id: int, text: str, now: datetime | None = None) -> Memory | None:
        """How something turned out ("考得还行，估计八十来分"), hung on the memory of the thing
        itself with the day he said it (memory v3 §B1), instead of a memory of its own that fades
        in a week. The text stays as it was; a later result replaces an earlier one. Hearing it is
        using the memory once. None when the result holds a secret: nothing is written."""
        if secret(text):
            return None
        now = now or datetime.now()
        said = f"（{now.month}月{now.day}日说的）"
        self.conn.execute("UPDATE memories SET outcome = ? WHERE id = ?", (text.strip() + said, memory_id))
        self.conn.commit()
        return self.touch(memory_id, now)

    def awaiting_outcome(self, chat: str, now: datetime, *, also: set[int] | frozenset[int] = frozenset()
                         ) -> list[Memory]:
        """What the close may hang a result on (memory v3 §B2): first the memories the follow-ups
        she asked in this chat are about (`also`), then his events of the last OUTCOME_DAYS that
        end in a result (an exam, an interview, a move) and that this chat touched (one of those
        words or one of its tags comes up in `chat`), latest first. Nothing still to come: a result
        needs the day to have passed. A promise is not here; it is kept or dropped (`settle`)."""
        since = (now.date() - timedelta(days=OUTCOME_DAYS)).isoformat()
        today = now.date().isoformat()
        asked = [m for m in self.alive() if m.id in also and not m.pact]
        touched = []
        for m in reversed(self.alive("event")):
            words = OUTCOME_WORDS.findall(m.text)
            if (m.id not in also and words and not m.pact and not m.text.lstrip().startswith("我")
                    and since <= (m.happened_on or m.created[:10]) <= today
                    and any(w in chat for w in [*words, *(t for t in m.tags if len(t) >= 2)])):
                touched.append(m)
        return (asked + touched)[:OUTCOMES_SHOWN]

    def source_for(self, text: str, episode_id: int) -> Memory | None:
        """The note of the same chat a follow-up is about ("演唱会看得怎么样" and the concert he
        mentioned, memory v3 §B1): of his events and facts from that chat whose tag the follow-up
        says, or that it overlaps at SOURCE_LINK or more, the one it overlaps most. Never an open
        promise: that link is `pact_for`'s, stricter, since such a follow-up never runs out."""
        notes = [m for m in self.alive() if m.source_episode == episode_id and m.kind in ("event", "fact")
                 and m.pact_state != "open"
                 and (overlap(text, m.text) >= SOURCE_LINK or any(len(t) >= 2 and t in text for t in m.tags))]
        return max(notes, key=lambda m: (overlap(text, m.text), -m.id), default=None)

    def howto_card(self, limit: int = 8) -> list[Memory]:
        """How to get along with him: the rules she has drawn, always in mind (decision 11).
        A rule she saw is outdated (weakened) leaves the card until it is seen again."""
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE superseded_by IS NULL AND kind = 'howto' AND stability > ?"
            " ORDER BY importance DESC, stability DESC, id DESC LIMIT ?", (st.WEAKENED_DAYS, limit)
        )
        return [_from_row(r) for r in rows]

    def planned_for(self, days: list[date]) -> list[Memory]:
        """Things he said would happen on these days (an exam, a trip), said before the day came:
        what the "today" section reminds her of (memory v3 §B3). A note written on the day it is
        about is not a plan, it is news, and the chat it came from is still in front of her.
        Events only: a fact is who he is, not something that happens on a day."""
        wanted = [d.isoformat() for d in days]
        rows = self.conn.execute(
            f"SELECT * FROM memories WHERE superseded_by IS NULL AND kind = 'event'"
            f" AND happened_on IN ({', '.join('?' * len(wanted))}) AND substr(created, 1, 10) < happened_on"
            " ORDER BY happened_on, id", wanted)
        return [_from_row(r) for r in rows]

    def seen_recently(self, now: datetime, days: int = 7) -> list[Memory]:
        """World memories from the last `days`, newest first (also the URLs not to reopen)."""
        since = iso(now - timedelta(days=days))
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE kind = 'world' AND created >= ? ORDER BY id DESC", (since,)
        )
        return [_from_row(r) for r in rows]

    def former(self, memory_id: int) -> Memory | None:
        """The memory this one replaced, if any ('你之前说是周五来着'): only a correction or an
        update, never a source it was merged from or a rule a cap pushed out."""
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE superseded_by = ? ORDER BY id DESC", (memory_id,)
        ).fetchall()
        new = self.get(memory_id) if rows else None
        for old in map(_from_row, rows):
            if (old.why or why_before_v3(old, new)) in SHOWN_AS_FORMER:
                return old
        return None

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

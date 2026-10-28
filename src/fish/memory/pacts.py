"""Promises between them and the nickname he gave her (memory v3 §B2 D1/D2), found by fixed
words in a note, not by the label the model picked.

The model filed "期末考完去海边，拍海的照片给大肥鱼看" as 日常 because it reads like a plan, and
the nickname 胖鱼 only ever reached her as an unconfirmed rule. A note from a chat (or its close)
that promises her something, or that she promised him, becomes a pact: pinned, 一辈子, and
`pact_state = open` until he keeps it or says it is off. The nickname becomes a pinned fact.

Only notes heard from him count (`HEARD`): what she writes while browsing, at night or in her
free time ("我答应上午给他带点好玩的事") is her own plan, never a pact.
Pure functions, no database, no model.
"""

from __future__ import annotations

import re
from typing import Iterable

HEARD = ("chat", "close")  # where a note can be a pact or a nickname from
PROMISE_KINDS = ("fact", "event", "self")
WHO = ("him", "her", "both")  # who promised: he did, she did, they agreed together
STATES = ("open", "kept", "dropped")
PACTS_SHOWN = 6

PROMISE = re.compile(r"答应|承诺|说好|说定|约好|保证|发誓|一言为定|拉钩")
# "等期末考完我去海边玩，给你拍海的照片": a promise without a promise word, once a condition
# ("等…完 / 到 / 以后 / 那天", or 了 closing its clause: "等论文交了，带我去") is followed by
# something done for her (or by her for him) that has not happened yet: "给你拍", not
# "给我发了个哭脸". "他等公交等了好久" is waiting, not a condition: no 等了 / 等着, no second 等,
# no 了 mid-clause.
# Any thing done (给我录一段, 帮他拦着), not a list of verbs: 录 was missing from the list.
DONE_FOR = (r"(?:给你|给我|给大肥鱼|我给他|帮我|我帮他)(?!们)[^\s，。！？；,.!?]"
            r"|带你|陪你|带我|陪我|我陪他|我带他")
WAIT_THEN = re.compile(r"等(?![了着过])[^，。！？；等]{1,15}?"
                       r"(?:完|到|好|以后|之后|那天|那时|的时候|回来|了(?=[，,\s]))"
                       rf"[^。！？；]{{0,24}}?(?:{DONE_FOR})(?![了过])")
# the promise is to her ("答应我", "给大肥鱼看"), or hers ("我答应他", "他让我答应"). 跟我说 /
# 和我说 is only him telling her ("他跟我说他和导师约好了"); 和我说好 is a promise.
TO_HER = re.compile(r"给我|(?:跟|和|对)我(?![说讲](?![好定]))|向我|陪我|带我|答应我|答应你|大肥鱼"
                    r"|咱俩|我俩|我们俩|我答应|我保证|我发誓|我承诺|让我答应|我(?:要|会|就|来)?[给帮陪带]他"
                    r"|(?:说好|说定)了?[^，。！？；]{0,16}?我")
# "他答应室友周末搬走", "他跟导师保证了下周交初稿": promised to somebody else, the third person
# right after the promise word or right before it
THIRD = (r"室友|舍友|同学|朋友|同事|老板|领导|组长|老师|导师|教练|女朋友|男朋友|对象|家里|别人|人家"
         r"|队友|学长|学姐|师兄|师姐|他们|她们|客户|房东|爸|妈|哥|姐|弟|妹")
TO_SOMEONE_ELSE = re.compile(rf"(?:{PROMISE.pattern})(?:了|过)?(?:要)?(?:[他她]的?)?(?:{THIRD})")
WITH_SOMEONE_ELSE = re.compile(rf"(?:跟|和|对|向|与)(?:[他她]的?)?(?:{THIRD})[^，。！？；我你]{{0,3}}$")
# "说好了等他……那天我写首诗": she is the one who does it, not 给我 / 带我 / 陪我 (his doing)
HERS = re.compile(r"我答应|我保证|我发誓|我承诺|让我答应|我(?:要|会|就|来)?[给帮陪带]他"
                  r"|(?:说好|说定)了?[^，。！？；]{0,16}?(?<![给带陪跟和对向])我(?!们)")
TOGETHER = re.compile(r"咱俩|我俩|我们俩|约好|拉钩|一言为定|说好一起")
# "他给我起的外号是胖鱼", "他管我叫胖鱼". Not a bare 叫我 ("他叫我别熬夜"), not 喊我 unless a
# name in quotes follows ("他喊我早点睡"), not somebody else's nickname ("他室友外号叫大头").
NICKNAME = re.compile(r"管我叫|管你叫|喊我[“\"「『‘]")
NICKNAME_WORD = re.compile(r"外号|昵称")
FOR_HER = re.compile(r"给我|叫我|管我|喊我|我的|给你|叫你|你的|大肥鱼")


# A note that quotes him ("他说：「你答应我……」", "他说我答应你……"): the persons inside are his,
# so his "我" is him and his "你" is her (his_line).
QUOTED = re.compile(r"他(?:说|讲)\s*(?:[:：]\s*[「“\"『]?|[「“\"『])(?P<q>[^」”\"』]+)"
                    r"|他(?:说|讲)(?P<q2>我(?:答应你|保证|发誓|承诺)[^。！？]*)")
# A rule or an insight that is in fact a promise ("他答应我，……买到后……"): the model files some
# promises as what it saw in him. Only one that opens by saying the two of them agreed.
OPENS_AS_PROMISE = re.compile(r"^(?:他|我)?(?:答应|让我答应|和我说好|跟我说好|和我约好|跟我约好|我们说好|我俩说好)")


def promise(text: str, kind: str) -> str | None:
    """Who promised (WHO) when this note is a promise between them; None otherwise."""
    if kind not in PROMISE_KINDS:
        return None
    if (quoted := QUOTED.search(text)) is not None and \
            (who := his_line(quoted.group("q") or quoted.group("q2"))) is not None:
        return who
    worded = any(not TO_SOMEONE_ELSE.match(text, m.start())
                 and not WITH_SOMEONE_ELSE.search(text[max(0, m.start() - 12):m.start()])
                 for m in PROMISE.finditer(text))
    if not (worded and (kind == "self" or TO_HER.search(text)) or WAIT_THEN.search(text)):
        return None
    if HERS.search(text):
        return "her"
    if TOGETHER.search(text):
        return "both"
    return "her" if kind == "self" else "him"  # her own doings are hers to keep


def ruled_promise(text: str) -> bool:
    """An insight or a howto that is a promise between them, to be kept as a fact (a rule would
    start unconfirmed and fade in weeks)."""
    return bool(OPENS_AS_PROMISE.match(text.strip()) or WAIT_THEN.search(text)) and promise(text, "fact") is not None


# --- his own line (memory v3 §14) -------------------------------------------------------------
# His words, not a note: "我" is him and "你" is her. A promise he makes or asks of her, said in so
# many words. Not a question about one ("你答应过我啥来着"), not one already made (答应过), not one
# he cannot make (保证不了), not one to or from somebody else (我答应室友, 我妈让我保证).
LINE_WORD = r"答应|承诺|说好|说定|约好|约定|保证|发誓|一言为定|拉钩|不许赖|不准赖|说话算话"
LINE_PROMISE = re.compile(rf"(?:{LINE_WORD})(?![过的不])")
LINE_ASKING = re.compile(r"[?？]\s*$|(?:吗|啥|什么|来着|是啥|没有)[。！!…~～\s]*$|还记得|记不记得")
LINE_SURE = re.compile(r"说定了|一言为定|拉钩|不许赖|不准赖")  # said like this it is no question
LINE_ELSE = re.compile(rf"(?:{LINE_WORD})(?:了|过)?(?:要)?(?:[他她]的?)?(?:{THIRD})"
                       rf"|(?:跟|和|对|向|与)(?:[他她]的?)?(?:{THIRD})[^，。！？]{{0,4}}(?:{LINE_WORD})"
                       rf"|(?:{THIRD})[^，。！？]{{0,3}}[让叫要]我")
LINE_HERS = re.compile(r"你答应|答应我|你保证|你发誓|你承诺|你得|你要给我|你给我|你帮我|你陪我|你带我|你先"
                       r"|说好了?你|你可别忘|你记得给我")
LINE_HIS = re.compile(r"我答应你|我向你保证|我保证|我发誓|我承诺|答应你|我给你|我带你|我陪你|我帮你|说好了?我")
LINE_BOTH = re.compile(r"咱俩|我俩|咱们|我们|一起")
LINE_WAIT = re.compile(r"等(?![了着过])[^，。！？；等]{1,15}?(?:完|到|好|以后|之后|那天|那时|的时候|回来|了(?=[，,\s]))"
                       r"[^。！？；]{0,24}?(?:(我给你|给你|带你|陪你)|(你给我|你带我|你陪我))[^\s，。！？；](?![了过])")


def his_line(line: str) -> str | None:
    """Who promised (WHO) when his own line makes a promise between them; None otherwise."""
    line = line.strip()
    if LINE_ELSE.search(line):
        return None
    if LINE_ASKING.search(line) and not LINE_SURE.search(line):
        return None
    if LINE_PROMISE.search(line):
        if LINE_HERS.search(line):
            return "her"
        if LINE_HIS.search(line):
            return "him"
        return "both" if LINE_BOTH.search(line) else None
    if (m := LINE_WAIT.search(line)) is not None:
        return "him" if m.group(1) else "her"
    return None


# "你答应过我什么来着", "我欠你个啥": he asks what was promised. Then the promises already kept or
# called off are shown with the open ones (memory v3 §14).
ASKS_PACT = re.compile(r"答应|(?<![也或允不准])许(?![多久])|保证|承诺|应承|约定|约好|说好|说定|欠你|欠我|拉钩")
ASKING = re.compile(r"[?？]|吗|啥|什么|来着|哪|记得|忘了")


def asks_pact(line: str) -> bool:
    return bool(ASKS_PACT.search(line) and ASKING.search(line))


def nickname(text: str) -> bool:
    """A note saying what he calls her."""
    return bool(NICKNAME.search(text) or NICKNAME_WORD.search(text) and FOR_HER.search(text))


# What a promise waits for: "等他X拿到那天", "答应我，X买到后" (memory v3 §14).
CONDITION = re.compile(r"等(?![了着过])(?P<a>[^，。！？；等]{1,15}?)(?P<done>完|到|好|以后|之后|那天|那时|的时候|回来)"
                       r"|(?:答应|说好|约好|说定)[我你他]?[，,:：]?\s*(?P<b>[^，。！？；]{2,15}?)(?:以后|之后|后|那天|的时候)")
CONDITION_RUN = 3  # this many characters in a row of the condition in his line is it happening


def condition(text: str) -> str:
    """What the promise waits for, without who: "驾照拿到" of "等他驾照拿到那天"; "" when none."""
    m = CONDITION.search(text)
    if m is None:
        return ""
    cond = m.group("a") + m.group("done") if m.group("a") is not None else m.group("b")
    return re.sub(r"^等?[他我你]?", "", cond)


def _run_in(a: str, b: str) -> str:
    """The longest run of letters or digits of `a` that is also in `b`."""
    best = ""
    for i in range(len(a)):
        for j in range(i + len(best) + 1, len(a) + 1):
            piece = a[i:j]
            if not piece.isalnum() or piece not in b:
                break
            best = piece
    return best


def triggered(line: str, pacts: Iterable) -> dict[int, str]:
    """Open pacts his line touches, id -> the trigger he said ("驾照"): a tag of the pact found
    word for word in his line (the tags are the model's, written with the note), or what the
    promise waits for, CONDITION_RUN characters of it in a row ("驾照拿到了！" for a promise
    "等他驾照拿到那天……", whatever its tags)."""
    out: dict[int, str] = {}
    for p in pacts:
        hit = next((t for t in sorted(p.tags, key=len, reverse=True) if len(t) >= 2 and t in line), None)
        if not hit and len(run := _run_in(condition(p.text), line)) >= CONDITION_RUN:
            hit = run
        if hit:
            out[p.id] = hit
    return out

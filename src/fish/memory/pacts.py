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
DONE_FOR = (r"(?:给你|给我|给大肥鱼|我给他)(?:拍|带|讲|写|做|买|寄|唱|画|看|煮|弹|过|准备)"
            r"|带你|陪你|带我|陪我|我陪他|我带他")
WAIT_THEN = re.compile(r"等(?![了着过])[^，。！？；等]{1,15}?"
                       r"(?:完|到|好|以后|之后|那天|那时|的时候|回来|了(?=[，,\s]))"
                       rf"[^。！？；]{{0,24}}?(?:{DONE_FOR})(?![了过])")
# the promise is to her ("答应我", "给大肥鱼看"), or hers ("我答应他", "他让我答应"). 跟我说 /
# 和我说 is only him telling her ("他跟我说他和导师约好了"); 和我说好 is a promise.
TO_HER = re.compile(r"给我|(?:跟|和|对)我(?![说讲](?![好定]))|向我|陪我|带我|答应我|答应你|大肥鱼"
                    r"|咱俩|我俩|我们俩|我答应|我保证|我发誓|我承诺|让我答应")
# "他答应室友周末搬走", "他跟导师保证了下周交初稿": promised to somebody else, the third person
# right after the promise word or right before it
THIRD = (r"室友|舍友|同学|朋友|同事|老板|领导|组长|老师|导师|教练|女朋友|男朋友|对象|家里|别人|人家"
         r"|队友|学长|学姐|师兄|师姐|他们|她们|客户|房东|爸|妈|哥|姐|弟|妹")
TO_SOMEONE_ELSE = re.compile(rf"(?:{PROMISE.pattern})(?:了|过)?(?:要)?(?:[他她]的?)?(?:{THIRD})")
WITH_SOMEONE_ELSE = re.compile(rf"(?:跟|和|对|向|与)(?:[他她]的?)?(?:{THIRD})[^，。！？；我你]{{0,3}}$")
HERS = re.compile(r"我答应|我保证|我发誓|我承诺|让我答应|我给他|我陪他|我带他|我帮他")
TOGETHER = re.compile(r"咱俩|我俩|我们俩|约好|拉钩|一言为定|说好一起")
# "他给我起的外号是胖鱼", "他管我叫胖鱼". Not a bare 叫我 ("他叫我别熬夜"), not 喊我 unless a
# name in quotes follows ("他喊我早点睡"), not somebody else's nickname ("他室友外号叫大头").
NICKNAME = re.compile(r"管我叫|管你叫|喊我[“\"「『‘]")
NICKNAME_WORD = re.compile(r"外号|昵称")
FOR_HER = re.compile(r"给我|叫我|管我|喊我|我的|给你|叫你|你的|大肥鱼")


def promise(text: str, kind: str) -> str | None:
    """Who promised (WHO) when this note is a promise between them; None otherwise."""
    if kind not in PROMISE_KINDS:
        return None
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


def nickname(text: str) -> bool:
    """A note saying what he calls her."""
    return bool(NICKNAME.search(text) or NICKNAME_WORD.search(text) and FOR_HER.search(text))


def triggered(line: str, pacts: Iterable) -> dict[int, str]:
    """Open pacts his line touches, id -> the trigger he said ("驾照"): a tag of the pact
    found word for word in his line. The tags are the model's, written with the note."""
    out: dict[int, str] = {}
    for p in pacts:
        hit = next((t for t in sorted(p.tags, key=len, reverse=True) if len(t) >= 2 and t in line), None)
        if hit:
            out[p.id] = hit
    return out

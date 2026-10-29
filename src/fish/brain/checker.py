"""The checker (decision 38): before a line of hers that talks about her home goes out, one
more call holds it against the room's own record and mends only what does not match ("冰箱里那
本《雪国》" when the book was on the windowsill). The room is code and never wrong about itself;
it is her telling of it that slips. Anything the checker cannot do leaves her line as it was."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from fish.brain.ask import ask_json
from fish.brain.llm import LLM
from fish.brain.parse import texting
from fish.brain.prompt import HOME_WORDS

FIRST = "（他没说话，是她主动发的）"
# her words that may be about her home: the room words, and a book or something put somewhere
# ("那本《雪国》"), but not 图书馆, 放心, 放假
CHECK_WORDS = re.compile(HOME_WORDS.pattern + r"|(?<!图)书(?!馆)|窗|放(?!心|假|学|松|弃)|出门|路上|到家|回来|叠|洗")


def talks_of_home(said: str) -> bool:
    return bool(said.strip()) and CHECK_WORDS.search(said) is not None


def check_home(llm: LLM, record: str, his: str, said: str) -> tuple[str, str]:
    """Her line, mended where it does not match the record; and why, "" when nothing changed."""
    if not record or not talks_of_home(said):
        return said, ""
    data = ask_json(llm, "home_check", record=record, his=his or FIRST, said=said,
                    temperature=0.0, max_tokens=500)
    if not data or data.get("ok") is not False:
        return said, ""
    fixed = texting(str(data.get("fixed") or ""))
    if not fixed or fixed == said or not _a_mend(said, fixed, record):
        return said, ""
    return fixed, str(data.get("why") or "").strip()[:120]


SWAP_AT_MOST = 12  # characters one swapped-in piece may have


def _a_mend(said: str, fixed: str, record: str) -> bool:
    """Only a cut, or a few words swapped for words the record has word for word ("冰箱里" ->
    "窗台上"). Free rewording made new slips in the 10-29 trials ("昨晚上" became "中午" on the
    next morning; "米和肉" came back as five things she had not bought)."""
    for tag, _, _, j1, j2 in SequenceMatcher(None, said, fixed, autojunk=False).get_opcodes():
        piece = fixed[j1:j2].strip()
        if tag in ("replace", "insert") and piece and (len(piece) > SWAP_AT_MOST or piece not in record):
            return False
    return True

"""Secrets never get written down (memory v3 §B2 S0; the persona's bottom line).

A door code, a password, a card number: even when he says "你帮我记着", she does not keep it.
Every write path checks here: a note, a correction, an outcome or a follow-up that holds a secret
is refused whole; a summary, a gist or a diary entry loses the sentence that holds one.
Plain rules, no model.
"""

from __future__ import annotations

import re

DIGITS = re.compile(r"\d{6,}")  # a code, a card, a phone number; dates are written with separators
WORDS = re.compile(r"密码|验证码|卡号|证件|身份证|口令")
SENTENCE_END = re.compile(r"(?<=[。！？!?；;\n])")


def secret(text: str) -> bool:
    """True when the text holds six or more digits in a row, or a word that comes with a secret."""
    return bool(DIGITS.search(text) or WORDS.search(text))


def redact(text: str) -> str:
    """The text without the sentences that hold a secret; whatever else it says is kept."""
    if not secret(text):
        return text
    kept = [s for s in SENTENCE_END.split(text) if not secret(s)]
    return "".join(kept).strip()

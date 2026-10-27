"""Turn docs/persona_zh.md into prompt fragments.

The file is who she is. Two parts come out of it: the base persona (everything except the
header card and the stage section) and the stage rules, one block per closeness stage,
of which only the current one is shown to her (decision 11).
"""

from __future__ import annotations

import re
from pathlib import Path

from fish.config import PERSONA_PATH, owner_words

STAGE_HEADING = "## 和他的熟悉程度"
_STAGE_LINE = re.compile(r"^###\s*([^\s（(]+)")


def split_persona(text: str) -> tuple[str, dict[str, str]]:
    """Returns (base persona without the card and the stage section, {stage name: rules})."""
    lines = [ln for ln in text.splitlines() if not ln.startswith(">")]
    base: list[str] = []
    stages: dict[str, str] = {}
    current: str | None = None
    in_section = False
    for ln in lines:
        if ln.startswith(STAGE_HEADING):
            in_section = True
            current = None
            continue
        if in_section and ln.startswith("## "):
            in_section = False
        if in_section:
            m = _STAGE_LINE.match(ln)
            if m:
                current = m.group(1)
                stages[current] = ""
            elif current and ln.strip():
                stages[current] += ln.rstrip() + "\n"
            continue
        base.append(ln)
    return "\n".join(base).strip(), {k: v.strip() for k, v in stages.items()}


def load_persona(path: Path = PERSONA_PATH) -> str:
    return owner_words(split_persona(path.read_text(encoding="utf-8"))[0])


def load_stages(path: Path = PERSONA_PATH) -> dict[str, str]:
    return {k: owner_words(v) for k, v in split_persona(path.read_text(encoding="utf-8"))[1].items()}

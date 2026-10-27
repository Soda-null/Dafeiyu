"""Keep the prompt under a character budget (docs/memory_design_zh.md §2).

Cut order when over budget: recalled memories (from the weakest), then the running
summary, then the oldest window turns (never below MIN_TURNS), then the follow-ups.
Persona, profile, diary and the state line are never cut.
"""

from __future__ import annotations

from fish.memory import Recalled, Turn

DEFAULT_LIMIT = 6000
MIN_TURNS = 4
TURN_OVERHEAD = 4  # role marker etc.


def chars(parts: dict[str, str], window: list[Turn], user_text: str) -> int:
    return (sum(len(v) for v in parts.values())
            + sum(len(t.text) + TURN_OVERHEAD for t in window) + len(user_text))


def fit(
    recalled: list[Recalled],
    summary: str,
    window: list[Turn],
    followups_text: str,
    fixed_chars: int,
    user_text: str,
    *,
    limit: int = DEFAULT_LIMIT,
    render_recalled=None,
) -> tuple[list[Recalled], str, list[Turn], str]:
    """Return possibly shortened (recalled, summary, window, followups_text)."""
    render_recalled = render_recalled or (lambda rs: "\n".join(r.memory.text for r in rs))

    def total() -> int:
        parts = {"r": render_recalled(recalled), "s": summary, "f": followups_text}
        return fixed_chars + chars(parts, window, user_text)

    while total() > limit and recalled:
        recalled = recalled[:-1]
    if total() > limit and summary:
        summary = ""
    while total() > limit and len(window) > MIN_TURNS:
        window = window[1:]
    if total() > limit and followups_text:
        followups_text = ""
    return recalled, summary, window, followups_text

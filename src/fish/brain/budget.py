"""Keep the prompt near a character budget (docs/memory_design_zh.md §2).

The day's chat is never cut here (decision 32): what was said today is in front of her in
full, like a person's day, and has its own, much larger limit (DAY_LIMIT, prompt.fit_day).
So the budget is soft: over it, only recalled memories are cut, from the weakest down to the
strongest one, then the follow-ups. When he asks "还记得吗" the answer is in what was
recalled, so the best memory is never cut (the recall budget already keeps it short).
Persona, profile, diary and the state line are never cut either.
"""

from __future__ import annotations

from fish.memory import Recalled, Turn

DEFAULT_LIMIT = 6000
DAY_LIMIT = 15000  # characters of today's chat kept word for word (decision 32)
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
    """Return possibly shortened (recalled, summary, window, followups_text); the summary
    (what came earlier today) and the window are returned whole."""
    render_recalled = render_recalled or (lambda rs: "\n".join(r.memory.text for r in rs))

    def total() -> int:
        parts = {"r": render_recalled(recalled), "s": summary, "f": followups_text}
        return fixed_chars + chars(parts, window, user_text)

    while total() > limit and len(recalled) > 1:
        recalled = recalled[:-1]
    if total() > limit and followups_text:
        followups_text = ""
    return recalled, summary, window, followups_text

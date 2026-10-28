"""Keep the prompt under a character budget (docs/memory_design_zh.md §2).

Cut order when over budget: recalled memories from the weakest down to KEEP_RECALLED, then
the running summary, then the oldest window turns (never below MIN_TURNS), then recalled
memories down to the strongest one, then the follow-ups. When he asks "还记得吗" the answer is
in what was recalled, not in older turns of this chat, so the best memory is never cut (the
recall budget already keeps it short). Persona, profile, diary and the state line are never cut.
"""

from __future__ import annotations

from fish.memory import Recalled, Turn

DEFAULT_LIMIT = 6000
MIN_TURNS = 4
KEEP_RECALLED = 2  # memories kept until the summary and the older turns are gone
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

    while total() > limit and len(recalled) > KEEP_RECALLED:
        recalled = recalled[:-1]
    if total() > limit and summary:
        summary = ""
    while total() > limit and len(window) > MIN_TURNS:
        window = window[1:]
    while total() > limit and len(recalled) > 1:
        recalled = recalled[:-1]
    if total() > limit and followups_text:
        followups_text = ""
    return recalled, summary, window, followups_text

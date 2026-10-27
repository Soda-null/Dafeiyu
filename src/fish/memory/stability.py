"""The forgetting math (docs/memory_design_zh.md §5.3). Pure functions, no I/O.

A memory has a stability S in days. Its retrievability R = exp(-t/S) is the chance she
can recall it t days after she last used it, without a reminder. Recalling it raises S,
and raises it more when R had dropped low (the spacing effect). Importance 10 pins S
to infinity. The numbers here are parameters, not truths: BASE is the one knob that
sets how fast everything fades.
"""

from __future__ import annotations

import math

BASE = 2.1  # S0 = BASE ** importance, in days
EMOTION_THRESHOLD = 0.6  # |valence| at or above this ...
EMOTION_BONUS = 1.5  # ... multiplies S0 by this
RECALL_GAIN = 1.5  # S *= 1 + RECALL_GAIN * (1 - R) on each recall
MERGE_GAIN = 1.3  # merged duplicates: S = max(S) * MERGE_GAIN
PINNED_IMPORTANCE = 10

FUZZY_R = 0.5  # below: she is unsure ("好像是……")
FREE_RECALL_R = 0.1  # below: she cannot bring it up herself
CUED_RECALL_R = 0.02  # below: even a strong reminder fails

INFINITE = float("inf")


def clamp_importance(importance: int) -> int:
    return max(1, min(PINNED_IMPORTANCE, int(importance)))


def initial_stability(importance: int, valence: float = 0.0) -> float:
    importance = clamp_importance(importance)
    if importance >= PINNED_IMPORTANCE:
        return INFINITE
    s = BASE**importance
    if abs(valence) >= EMOTION_THRESHOLD:
        s *= EMOTION_BONUS
    return s


def retrievability(stability: float, days: float) -> float:
    if stability == INFINITE:
        return 1.0
    if stability <= 0:
        return 0.0
    return math.exp(-max(0.0, days) / stability)


def after_recall(stability: float, r: float) -> float:
    if stability == INFINITE:
        return stability
    r = max(0.0, min(1.0, r))
    return stability * (1 + RECALL_GAIN * (1 - r))


def after_merge(*stabilities: float) -> float:
    s = max(stabilities)
    return s if s == INFINITE else s * MERGE_GAIN


def days_until(stability: float, r: float) -> float:
    """Days after which retrievability falls to r (the design table is built from this)."""
    if stability == INFINITE:
        return INFINITE
    return -stability * math.log(r)

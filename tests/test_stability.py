"""The forgetting math matches the table in docs/memory_design_zh.md §5.3."""

import pytest

from fish.memory import stability as st

# importance -> (S0 days, days until fuzzy, days until she cannot recall alone), from the design table
TABLE = {
    1: (2.1, 1.5, 5), 2: (4.4, 3, 10), 3: (9.3, 6, 21), 4: (19, 13, 45), 5: (41, 28, 95),
    6: (86, 59, 200), 7: (180, 125, 415), 8: (378, 260, 870), 9: (794, 550, 1830),
}


@pytest.mark.parametrize("importance,expected", TABLE.items())
def test_design_table(importance, expected):
    s0, fuzzy_days, gone_days = expected
    s = st.initial_stability(importance)
    assert s == pytest.approx(s0, rel=0.03)
    assert st.days_until(s, st.FUZZY_R) == pytest.approx(fuzzy_days, rel=0.08)
    assert st.days_until(s, st.FREE_RECALL_R) == pytest.approx(gone_days, rel=0.05)


def test_importance_10_is_pinned_forever():
    s = st.initial_stability(10)
    assert s == st.INFINITE
    assert st.retrievability(s, 10_000) == 1.0
    assert st.after_recall(s, 0.01) == st.INFINITE


def test_emotion_makes_memories_stickier():
    assert st.initial_stability(5, valence=-0.8) == pytest.approx(st.initial_stability(5) * 1.5)
    assert st.initial_stability(5, valence=0.3) == st.initial_stability(5)


def test_recall_grows_stability_more_when_nearly_forgotten():
    s = 41.0
    barely = st.after_recall(s, r=0.1)
    fresh = st.after_recall(s, r=0.95)
    assert barely == pytest.approx(s * 2.35)
    assert fresh == pytest.approx(s * 1.075)


def test_three_mentions_of_a_medium_fact_last_a_year():
    """Importance 5, recalled each time it drops to R = 0.5 (about every S*0.69 days)."""
    s = st.initial_stability(5)
    elapsed = 0.0
    for _ in range(3):
        elapsed += st.days_until(s, 0.5)
        s = st.after_recall(s, 0.5)
    assert elapsed + st.days_until(s, st.FREE_RECALL_R) > 365


def test_merge_bonus_and_clamping():
    assert st.after_merge(10.0, 40.0) == pytest.approx(52.0)
    assert st.after_merge(10.0, st.INFINITE) == st.INFINITE
    assert st.clamp_importance(0) == 1 and st.clamp_importance(99) == 10

"""Urges to do things (decision 46): go out to the pier, to the flower shop. Each source adds
to how much she wants one place, with a line saying why; a place's urge comes up only once it
clears the threshold of its tier (texting him is at hand, the pier out of the door, the shops
a walk away), raised when she is tired or it is getting late."""

from __future__ import annotations

from datetime import datetime, timedelta

from fish.memory import MemoryStore
from fish.urges.rules import (AGAIN_AT_MOST, AGAIN_PER_DAY, BORED_LEVEL, BORED_PUSH, COOPED_AT_MOST, COOPED_PER_DAY,
                              EVENING_HOUR, EVENING_RAISE, NEW_PLACE, PLACES, PLAN, PLAN_DAYS, PLAN_WORDS,
                              THRESHOLDS, TIERS, TIRED_ENERGY, TIRED_RAISE)
from fish.urges.urge import HIM, Scene, Urge

COUNT = {1: "一", 2: "两", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七"}


def _days(s: Scene, stamp: str) -> float:
    return (s.now - datetime.fromisoformat(stamp)).total_seconds() / 86400


def _n(days: float) -> str:
    n = int(days)
    return COUNT.get(n, str(n))


def new_place(s: Scene, place: str) -> tuple[float, str] | None:
    if place in s.been:
        return None
    return NEW_PLACE, f"你还没去过{PLACES[place][0]}"


def again(s: Scene, place: str) -> tuple[float, str] | None:
    if place not in s.been:
        return None
    days = _days(s, s.been[place])
    if days < 1:
        return None
    return min(AGAIN_AT_MOST, AGAIN_PER_DAY * days), f"上回去{PLACES[place][0]}是{_n(days)}天前"


def cooped(s: Scene, place: str) -> tuple[float, str] | None:
    out = [v for k, v in s.been.items() if k != "since"] or [s.been.get("since")]
    if not out or out[0] is None:
        return None
    days = _days(s, max(out))
    if days < 1:
        return None
    return min(COOPED_AT_MOST, COOPED_PER_DAY * days), f"你{_n(days)}天没出过门了"


def bored(s: Scene, place: str) -> tuple[float, str] | None:
    return (BORED_PUSH, "你有点无聊") if s.mood.boredom >= BORED_LEVEL else None


def plan(s: Scene, place: str) -> tuple[float, str] | None:
    """She wrote down, in her own notes of the last few days, that she wants to go there."""
    since = s.now - timedelta(days=PLAN_DAYS)
    for m in MemoryStore(s.conn).alive("self"):
        if (datetime.fromisoformat(m.created) >= since and any(w in m.text for w in PLACES[place][2])
                and any(w in m.text for w in PLAN_WORDS)):
            return PLAN, f"你前两天想过：{m.text}"
    return None


SOURCES = (new_place, plan, cooped, again, bored)


def about_doing(s: Scene) -> list[Urge]:
    """How much she wants each place right now, and why, strongest first."""
    out = []
    for place in PLACES:
        found = [(source.__name__, x) for source in SOURCES if (x := source(s, place))]
        if found:
            strength = min(1.0, sum(x[0] for _, x in found))
            out.append(Urge(place, "+".join(name for name, _ in found),
                            f"{PLACES[place][1]}：" + "；".join(x[1] for _, x in found), round(strength, 2)))
    return sorted(out, key=lambda u: -u.strength)


def threshold(about: str, s: Scene) -> float:
    """How strong an urge must be to come up: by how far the thing is, more when she is tired
    or it is getting late (only for going out)."""
    tier = 0 if about == HIM else TIERS.get(about, 1)
    t = THRESHOLDS[min(tier, len(THRESHOLDS) - 1)]
    if tier >= 1:
        t += TIRED_RAISE if s.mood.energy < TIRED_ENERGY else 0.0
        t += EVENING_RAISE if s.now.hour >= EVENING_HOUR else 0.0
    return t


def wanted(s: Scene) -> list[Urge]:
    """The urges to do things that clear their threshold right now, strongest first."""
    return [u for u in about_doing(s) if u.strength >= threshold(u.about, s)]

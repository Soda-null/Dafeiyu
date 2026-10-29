"""Night steps 6–9: she sleeps (the mood node sets her morning from tonight's phase), a quiet
day is noted, old chats lose detail, his weekday habits are counted, follow-ups she never got
to ask are let go, the readable export is written, stickers in the inbox get her captions."""

from __future__ import annotations

from fish.memory import ProspectiveStore, count_patterns, he_wrote_between
from fish.msgs import Rested
from fish.routines.export import export_notebook
from fish.routines.night.context import Night
from fish.routines.stickers import adopt_inbox_stickers


def sleep(night: Night) -> None:
    """6. she sleeps; a day he never wrote is a quiet one for the relationship."""
    talked = he_wrote_between(night.conn, night.day_start, night.day_end)
    night.bus.publish(Rested(night.now, tone=night.phase.tone, drive=night.phase.drive))
    if not talked:
        night.rel.quiet_day(night.now)


def compress_old_chats(night: Night) -> None:
    night.report["compressed"] = night.episodes.compress(night.now)


def count_weekday_habits(night: Night) -> None:
    """6b. what he says on one weekday ("今天食堂有糖醋排骨" six Fridays running), counted by code
    and shown to her on that weekday; never an insight she saw herself (memory v3 §B6)"""
    patterns = count_patterns(night.conn, night.now, night.rel.patterns())
    night.rel.set_patterns(patterns, night.now)
    night.report["weekday_patterns"] = sum(p["status"] == "active" for p in patterns)


def let_go_of_unasked(night: Night) -> None:
    """7. a follow-up she never got to ask is let go, not written down as "我一直没问成他"
    (memory v3: those events crowded out what he said)"""
    night.report["expired"] = len(ProspectiveStore(night.conn).expire(night.now))


def export(night: Night) -> None:
    """8. the readable export"""
    if night.export_path is not None:
        export_notebook(night.conn, night.now, night.export_path)


def caption_stickers(night: Night) -> None:
    """9. stickers he dropped into the inbox folder get a caption in her words (decision 12)"""
    if night.brain is not None:
        night.report["stickers_added"] = adopt_inbox_stickers(night.brain, night.now)

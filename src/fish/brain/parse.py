"""Turn the model's JSON reply into a Reply. Tolerant: fences, stray text and bad fields
are forgiven; if nothing parses, the raw text becomes what she says and nothing is recorded.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date

from fish.memory import KINDS
from fish.memory import stability as st

MAX_NOTES = 5
MAX_NOTE_CHARS = 200
MOODS = ("开心", "平静", "无聊", "困", "饿", "烦", "难过", "好奇")
# "[sticker #1]", "[表情包#1]", "（表情包 1）", "[#1]" written into her words instead of the field
_STICKER_IN_TEXT = re.compile(r"[\[（(【]\s*(?:sticker|表情包?|贴纸)?\s*#?\s*(\d+)\s*[\]）)】]", re.I)


def split_sticker_placeholder(say: str) -> tuple[str, int | None]:
    """Remove a sticker placeholder from what she says; return the text and the id it named."""
    found = _STICKER_IN_TEXT.search(say)
    if not found:
        return say, None
    cleaned = _STICKER_IN_TEXT.sub("", say)
    cleaned = "\n".join(line.strip() for line in cleaned.splitlines() if line.strip())
    return cleaned, int(found.group(1))


@dataclass(frozen=True)
class Note:
    text: str
    kind: str = "event"
    importance: int = 5
    valence: float = 0.0
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class FollowupRequest:
    text: str
    due: str  # YYYY-MM-DD


@dataclass(frozen=True)
class Correction:
    old_id: int
    text: str


@dataclass
class Reply:
    say: str
    mood: str | None = None
    topic: str | None = None
    notes: list[Note] = field(default_factory=list)
    followups: list[FollowupRequest] = field(default_factory=list)
    asked: list[int] = field(default_factory=list)
    corrections: list[Correction] = field(default_factory=list)
    look: str | None = None  # something she wants to look up before answering
    seen: list[Note] = field(default_factory=list)  # world memories from what she just looked up
    image_note: str | None = None  # her one-line reading of a picture he sent
    keep_sticker: str | None = None  # caption, when she wants to keep his picture as a sticker
    sticker: int | None = None  # a sticker from her album to send with this reply
    parsed: bool = True


@dataclass
class EpisodeClose:
    summary: str
    gist: str
    importance: int = 5
    valence: float = 0.0
    notes: list[Note] = field(default_factory=list)
    followups: list[FollowupRequest] = field(default_factory=list)
    parsed: bool = True


_LENIENT = json.JSONDecoder(strict=False)  # raw newlines inside strings are forgiven


def extract_json(raw: str) -> dict | None:
    """The first JSON object anywhere in the text. The model sometimes writes a line or two
    of prose before (or after) the object, or a newline inside a string; neither should
    cost us the reply."""
    text = re.sub(r"```(?:json)?", "", raw).strip()
    start = text.find("{")
    while start != -1:
        try:
            data, _ = _LENIENT.raw_decode(text, start)
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        if isinstance(data, dict):
            return data
        start = text.find("{", start + 1)
    return None


def prose_only(raw: str) -> str:
    """What is left of a reply once every {...} block is removed: safe to show him."""
    text = re.sub(r"```(?:json)?", "", raw)
    text = re.sub(r"\{.*", "", text, flags=re.S)  # from the first brace on, even if unfinished
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _float(v, default=0.0, lo=-1.0, hi=1.0) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _int(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _valid_date(s) -> bool:
    try:
        date.fromisoformat(str(s))
        return True
    except ValueError:
        return False


def parse_notes(items, *, force_kind: str | None = None) -> list[Note]:
    notes: list[Note] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()[:MAX_NOTE_CHARS]
        if not text:
            continue
        kind = force_kind or item.get("kind", "event")
        if kind == "world" and not force_kind:
            kind = "event"  # facts about him never come in as "world"; world notes have their own field
        tags = item.get("tags", [])
        notes.append(Note(
            text=text,
            kind=kind if kind in KINDS else "event",
            importance=st.clamp_importance(_int(item.get("importance"), 5)),
            valence=_float(item.get("valence")),
            tags=tuple(str(t).strip() for t in tags if str(t).strip()) if isinstance(tags, list) else (),
        ))
        if len(notes) >= MAX_NOTES:
            break
    return notes


def parse_followups(items) -> list[FollowupRequest]:
    out: list[FollowupRequest] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        due = item.get("due")
        if text and _valid_date(due):
            out.append(FollowupRequest(text, str(due)))
    return out


def parse_reply(raw: str) -> Reply:
    data = extract_json(raw)
    if data is None or not isinstance(data.get("say"), str):
        return Reply(say=prose_only(raw), parsed=False)  # never his eyes on raw JSON
    mood = data.get("mood")
    topic = data.get("topic")
    asked = [i for i in (data.get("asked") or []) if isinstance(i, int)] \
        if isinstance(data.get("asked"), list) else []
    corrections = []
    for item in data.get("corrections") or []:
        if isinstance(item, dict) and isinstance(item.get("old_id"), int) \
                and str(item.get("text", "")).strip():
            corrections.append(Correction(item["old_id"], str(item["text"]).strip()[:MAX_NOTE_CHARS]))
    look = str(data.get("look") or "").strip()[:60]
    seen = [Note(n.text, "world", min(n.importance, 6), n.valence, n.tags)
            for n in parse_notes(data.get("seen"), force_kind="world")]
    image_note = str(data.get("image_note") or "").strip()[:80] or None
    keep_sticker = str(data.get("keep_sticker") or "").strip()[:80] or None
    sticker = data.get("sticker") if isinstance(data.get("sticker"), int) and data["sticker"] > 0 else None
    say, named = split_sticker_placeholder(data["say"].strip())
    if sticker is None and named:
        sticker = named
    return Reply(
        say=say,
        mood=mood if mood in MOODS else None,
        topic=str(topic).strip()[:20] if topic else None,
        notes=parse_notes(data.get("notes")),
        followups=parse_followups(data.get("followups")),
        asked=asked,
        corrections=corrections,
        look=look or None,
        seen=seen,
        image_note=image_note,
        keep_sticker=keep_sticker,
        sticker=sticker,
    )


def parse_episode_close(raw: str, fallback_summary: str) -> EpisodeClose:
    data = extract_json(raw)
    if data is None:
        return EpisodeClose(summary=fallback_summary, gist=fallback_summary[:60], parsed=False)
    return EpisodeClose(
        summary=str(data.get("summary") or fallback_summary).strip(),
        gist=str(data.get("gist") or "").strip()[:80] or fallback_summary[:60],
        importance=st.clamp_importance(_int(data.get("importance"), 5)),
        valence=_float(data.get("valence")),
        notes=parse_notes(data.get("notes")),
        followups=parse_followups(data.get("followups")),
    )

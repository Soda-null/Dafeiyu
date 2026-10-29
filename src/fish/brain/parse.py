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
MAX_OUTCOME_CHARS = 80
MOODS = ("开心", "平静", "无聊", "困", "饿", "烦", "难过", "好奇")
# "[sticker #1]", "[表情包#1]", "（表情包 1）", "[#1]" written into her words instead of the field
_STICKER_IN_TEXT = re.compile(r"[\[（(【]\s*(?:sticker|表情包?|贴纸)?\s*#?\s*(\d+)\s*[\]）)】]", re.I)


# What must never reach him as her words (checkup round two, docs/memory_v3_zh.md §14): the model,
# asked again in plain text, or writing its say, sometimes goes on past her one line. It plays his
# next turn ("user嗯 你猜", "他：那明天见", a chat-template token), writes the reply's fields out
# as text ("mood：平静"), or adds the whole JSON object. Every marker is our own machinery: the chat
# API's role names, the 他/你 labels of our transcripts, the field names of our output format.
_FAKE_TURN = re.compile(r"^\s*(?:<[|｜].*?[|｜]>|(?:user|assistant|system|sys|human)(?![a-z])|[他她你]\s*[:：])",
                        re.I)
_FIELD_LINE = re.compile(r"^\s*[\"']?(?:say|mood|topic|notes|followups|asked|corrections|look|seen|image_note"
                         r"|keep_sticker|sticker|心情|话题)[\"']?\s*[:：=]", re.I)
_OWN_LABEL = re.compile(r"^\s*(?:say|assistant|你)\s*[:：]\s*", re.I)


MAX_BUBBLES = 5  # messages one reply may come in; more are joined into the last


def texting(say: str) -> str:
    """Her line as people text on WeChat (decision 34): one short message per line, no full stop
    at the end of one; a full stop inside a line starts the next message. Past MAX_BUBBLES the
    rest goes into the last. The model is asked to write this way; this catches what slips."""
    lines: list[str] = []
    for line in say.splitlines():
        for part in re.split(r"(?<=。)", line):
            part = part.strip().rstrip("。").strip()
            if part:
                lines.append(part)
    if len(lines) > MAX_BUBBLES:
        lines = lines[:MAX_BUBBLES - 1] + ["，".join(lines[MAX_BUBBLES - 1:])]
    return "\n".join(lines)


def cut_say(text: str) -> tuple[str, bool]:
    """Her words without what she wrote past them, and whether a made-up turn was cut (then
    anything else in the reply may answer that made-up turn). Line 1 is hers: only a label of her
    own ("say:", "你：") and anything from a JSON object on are taken off it. From line 2 on, it ends
    at the first line that is a turn of the chat, a field of the reply or a JSON object."""
    lines = text.strip().splitlines()
    if not lines:
        return "", False
    first = _OWN_LABEL.sub("", lines[0])
    first = first.split('{"', 1)[0]
    kept, fake = [first], False
    for line in lines[1:]:
        if _FAKE_TURN.match(line):
            fake = True
            break
        if _FIELD_LINE.match(line) or line.lstrip().startswith("{") or '{"' in line:
            break
        kept.append(line)
    return "\n".join(kept).strip(), fake


def clean_say(text: str) -> str:
    """Her words, without a made-up turn, a field written out or a JSON object after them."""
    return cut_say(text)[0]


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
    about: str | None = None  # 路过 / 日常 / 本人 / 一辈子 (decision 21); None: the old importance rule
    arousal: float = 0.0  # how moved, 0-1


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
    do: str | None = None  # something in her room she starts now, as she says so (decision 35)
    do_arg: str = ""  # what she wants to buy, when `do` is the shop
    parsed: bool = True


@dataclass
class EpisodeClose:
    summary: str
    gist: str
    importance: int = 5
    valence: float = 0.0
    notes: list[Note] = field(default_factory=list)
    followups: list[FollowupRequest] = field(default_factory=list)
    pact_done: list[tuple[int, str]] = field(default_factory=list)  # (memory id, kept / dropped)
    outcomes: list[tuple[int, str]] = field(default_factory=list)  # (memory id, how it turned out)
    corrections: list[Correction] = field(default_factory=list)  # card facts this chat made untrue
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
            about=item.get("about") if item.get("about") in st.ABOUTS else None,
            arousal=max(0.0, min(1.0, _float(item.get("arousal")))),
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
        return Reply(say=clean_say(prose_only(raw)), parsed=False)  # never his eyes on raw JSON
    mood = data.get("mood")
    topic = data.get("topic")
    asked = [i for i in (data.get("asked") or []) if isinstance(i, int)] \
        if isinstance(data.get("asked"), list) else []
    corrections = parse_corrections(data.get("corrections"))
    look = str(data.get("look") or "").strip()[:60]
    seen = [Note(n.text, "world", min(n.importance, 6), n.valence, n.tags)
            for n in parse_notes(data.get("seen"), force_kind="world")]
    image_note = str(data.get("image_note") or "").strip()[:80] or None
    keep_sticker = str(data.get("keep_sticker") or "").strip()[:80] or None
    sticker = data.get("sticker") if isinstance(data.get("sticker"), int) and data["sticker"] > 0 else None
    said, fake = cut_say(data["say"])
    say, named = split_sticker_placeholder(said)
    if sticker is None and named:
        sticker = named
    # a say that went on into a made-up turn of his: what she noted may be what "he" said there
    return Reply(
        say=say,
        mood=mood if mood in MOODS else None,
        topic=str(topic).strip()[:20] if topic else None,
        notes=[] if fake else parse_notes(data.get("notes")),
        followups=[] if fake else parse_followups(data.get("followups")),
        asked=asked,
        corrections=[] if fake else corrections,
        look=look or None,
        seen=[] if fake else seen,
        image_note=image_note,
        keep_sticker=keep_sticker,
        sticker=sticker,
        do=str(data.get("do") or "").strip()[:12] or None if not fake else None,
        do_arg=str(data.get("do_arg") or "").strip()[:40] if not fake else "",
    )


def parse_retry(raw: str) -> Reply:
    """The plain-text second try, when the JSON reply gave nothing. Her line, cleaned. If the JSON
    object came after it anyway and nothing before it plays his turn, the object counts (the notes
    in it are hers, a promise among them); after a made-up turn of his it answers that turn, and
    nothing in it is kept."""
    before, fake = cut_say(prose_only(raw))
    if not fake and "{" in raw and (reply := parse_reply(raw)).parsed:
        reply.say = before or reply.say  # the line she wrote as text is the one asked for
        return reply
    return Reply(say=before, parsed=False)


def _salvage(raw: str, key: str) -> str:
    """One string field out of a JSON object that does not parse (cut off at max_tokens, a stray
    quote): what it says up to its closing quote, or to the end."""
    found = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)', raw, re.S)
    if not found:
        return ""
    try:
        return json.loads(f'"{found.group(1)}"', strict=False).strip()
    except json.JSONDecodeError:
        return found.group(1).replace('\\"', '"').strip()


def parse_episode_close(raw: str, fallback_summary: str) -> EpisodeClose:
    """A reply that does not parse still never loses the summary (memory v3 §B2): its summary
    field if one can be read, else the model's own prose, else `fallback_summary`; no notes."""
    data = extract_json(raw)
    if data is None:
        summary = _salvage(raw, "summary") or ("" if "{" in raw else prose_only(raw)) or fallback_summary
        return EpisodeClose(summary=summary[:400], gist=(_salvage(raw, "gist") or summary)[:60], parsed=False)
    return EpisodeClose(
        summary=str(data.get("summary") or fallback_summary).strip(),
        gist=str(data.get("gist") or "").strip()[:80] or fallback_summary[:60],
        importance=st.clamp_importance(_int(data.get("importance"), 5)),
        valence=_float(data.get("valence")),
        notes=parse_notes(data.get("notes")),
        followups=parse_followups(data.get("followups")),
        pact_done=parse_pact_done(data.get("pact_done")),
        outcomes=parse_outcomes(data.get("outcomes")),
        corrections=parse_corrections(data.get("corrections")),
    )


def parse_corrections(items) -> list[Correction]:
    """[{"old_id": 17, "text": "..."}]: what an old memory should say now. Whether the id is
    one she was shown is checked by the caller."""
    out: list[Correction] = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("old_id"), int) \
                and str(item.get("text", "")).strip():
            out.append(Correction(item["old_id"], str(item["text"]).strip()[:MAX_NOTE_CHARS]))
    return out


def parse_pact_done(items) -> list[tuple[int, str]]:
    """[{"id": 17, "state": "kept"}]: promises he kept or called off in this chat. Whether the
    id is one of the open promises she was shown is checked by the caller."""
    out: list[tuple[int, str]] = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("id"), int) and item.get("state") in ("kept", "dropped"):
            out.append((item["id"], item["state"]))
    return out


def parse_outcomes(items) -> list[tuple[int, str]]:
    """[{"id": 22, "text": "考得还行，估计八十来分"}]: how something she was shown turned out.
    Whether the id is one of them is checked by the caller."""
    out: list[tuple[int, str]] = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("id"), int) and str(item.get("text", "")).strip():
            out.append((item["id"], str(item["text"]).strip()[:MAX_OUTCOME_CHARS]))
    return out

"""Stickers he gives her (decision 12): pictures put into data/stickers/inbox/ (by hand,
by `fish stickers <folder>`, or from the Mac with `scripts/fish.sh stickers <folder>`) each
get a caption in her words, one look each, and move into the album. The nightly routine
takes up to ten; `fish stickers` takes them all now. The same picture twice is kept once.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from fish.memory import Sticker

if TYPE_CHECKING:
    from fish.brain import Brain

STICKER_TYPES = (".jpg", ".jpeg", ".png", ".gif", ".webp")
MAX_BYTES = 5_000_000  # bigger than any sticker; a photo that size is not one


@dataclass
class Adopted:
    added: list[Sticker] = field(default_factory=list)
    repeats: int = 0  # already in the album; removed from the inbox
    left: list[str] = field(default_factory=list)  # still in the inbox, with why


def inbox_of(brain: "Brain") -> Path:
    return brain.album.folder / "inbox"


def import_folder(src: Path, inbox: Path) -> int:
    """Copy every picture under `src` (subfolders too) into the inbox; the originals stay."""
    inbox.mkdir(parents=True, exist_ok=True)
    n = 0
    for path in sorted(p for p in src.rglob("*") if p.is_file() and p.suffix.lower() in STICKER_TYPES):
        target = inbox / path.name
        k = 1
        while target.exists():
            target = inbox / f"{path.stem}-{k}{path.suffix}"
            k += 1
        shutil.copyfile(path, target)
        n += 1
    return n


def adopt_inbox(brain: "Brain", now: datetime, limit: int | None = None) -> Adopted:
    from fish.brain import ask_json
    from fish.messages import data_url, sniff_mime

    inbox = inbox_of(brain)
    done = Adopted()
    if not inbox.is_dir():
        return done
    pictures = sorted(p for p in inbox.iterdir() if p.suffix.lower() in STICKER_TYPES)
    for path in pictures:
        if limit is not None and len(done.added) >= limit:
            break
        data = path.read_bytes()
        mime = sniff_mime(data)
        if mime is None:
            done.left.append(f"{path.name}：不是图片")
            continue
        if len(data) > MAX_BYTES:
            done.left.append(f"{path.name}：太大了（{len(data) // 1_000_000} MB）")
            continue
        if brain.album.has(data):
            path.unlink()
            done.repeats += 1
            continue
        reply = ask_json(brain.llm, "sticker_caption", persona=brain.persona, image=data_url(data),
                         temperature=0.9, max_tokens=200)
        caption = str((reply or {}).get("caption") or "").strip()
        if not caption:
            done.left.append(f"{path.name}：她没想好叫什么，下次再看")
            continue
        tags = reply.get("tags") if isinstance(reply.get("tags"), list) else []
        done.added.append(brain.album.add(data, mime, caption, tags=[str(t) for t in tags][:3],
                                          source="inbox", now=now))
        path.unlink()
    return done


def adopt_inbox_stickers(brain: "Brain", now: datetime, limit: int = 10) -> int:
    """The nightly step: up to `limit` a night."""
    return len(adopt_inbox(brain, now, limit).added)

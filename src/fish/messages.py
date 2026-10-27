"""What passes between a channel and the brain, and two picture helpers both need.
No dependencies, so the brain can use these without knowing any channel."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

MAGIC = ((b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG", "image/png"), (b"GIF8", "image/gif"),
         (b"RIFF", "image/webp"))


@dataclass(frozen=True)
class Incoming:
    text: str
    image: bytes | None = None  # a picture he sent, already decrypted


@dataclass(frozen=True)
class Outgoing:
    text: str
    sticker: Path | None = None  # a sticker from her album to send after the text
    sticker_caption: str = ""


Reply = Callable[[Incoming], Outgoing]


def sniff_mime(data: bytes) -> str | None:
    for magic, mime in MAGIC:
        if data.startswith(magic):
            return mime
    return None


def data_url(data: bytes) -> str:
    return f"data:{sniff_mime(data) or 'image/jpeg'};base64,{base64.b64encode(data).decode()}"

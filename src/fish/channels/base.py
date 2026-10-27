"""What every channel provides: a name, and a loop that hands Incomings to a reply function
and delivers the Outgoings. The records themselves live in fish.messages so the brain can
use them without importing any channel."""

from __future__ import annotations

from typing import Protocol

from fish.messages import Incoming, Outgoing, Reply

__all__ = ["Channel", "Incoming", "Outgoing", "Reply"]


class Channel(Protocol):
    name: str

    def run(self, reply: Reply) -> None: ...

"""The bus (docs/nodes_design_zh.md §2): nodes publish messages from `msgs.py`, other nodes
subscribe to them, and neither knows the other.

ROS's idea, not ROS: one process, plain function calls, in the order nodes subscribed. The
topic is the message's class, so a misspelt topic is an error at once, not silence. A
subscriber that fails does not stop the others; the failures come back together after
everyone has been called (or go to `on_error`, which the running service sets to log).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

Handler = Callable[[Any], None]


class BusError(Exception):
    """One or more subscribers failed on a message; `failures` holds (handler, exception)."""

    def __init__(self, message: Any, failures: list[tuple[Handler, BaseException]]) -> None:
        names = ", ".join(getattr(h, "__qualname__", repr(h)) for h, _ in failures)
        super().__init__(f"{type(message).__name__}: {len(failures)} subscriber(s) failed: {names}")
        self.message = message
        self.failures = failures


class Bus:
    def __init__(self, on_error: Callable[[Any, Handler, BaseException], None] | None = None) -> None:
        self._subscribers: dict[type, list[Handler]] = defaultdict(list)
        self.on_error = on_error  # None: raise BusError after every subscriber has run

    def subscribe(self, topic: type, handler: Handler) -> None:
        if not isinstance(topic, type):
            raise TypeError(f"a topic is a message class from fish.msgs, not {topic!r}")
        self._subscribers[topic].append(handler)

    def subscribers(self, topic: type) -> list[Handler]:
        return list(self._subscribers.get(topic, ()))

    def publish(self, message: Any) -> None:
        failures: list[tuple[Handler, BaseException]] = []
        for handler in self.subscribers(type(message)):
            try:
                handler(message)
            except Exception as e:  # one node's bug must not silence the rest
                if self.on_error is None:
                    failures.append((handler, e))
                else:
                    self.on_error(message, handler, e)
        if failures:
            raise BusError(message, failures) from failures[0][1]

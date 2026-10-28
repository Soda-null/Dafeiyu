"""The things she can do at home (decision 26): cook, wash up, make the bed, nap, go to the
vegetable shop. Only what would work is on the menu; the cottage's rules decide what it
changes, she only picks."""

from __future__ import annotations

from fish.brain.leisure.base import Activity, Choice, Kit, Material
from fish.cottage import Cottage
from fish.mood import MoodStore

KEY = "cottage"


class CottageActivity(Activity):
    key = KEY

    def __init__(self, cottage: Cottage) -> None:
        self.cottage = cottage

    def offer(self, kit: Kit) -> list[Choice]:
        mood = MoodStore.apply_clock(MoodStore(kit.conn).load(), kit.now)
        return [Choice(KEY, o.line, arg_hint=o.arg_hint, payload={"action": o.key})
                for o in self.cottage.offers(kit.now, mood.hunger, mood.energy)]

    def do(self, kit: Kit, choice: Choice, picks: list[int], arg: str) -> Material:
        change = self.cottage.act(choice.payload["action"], kit.now, arg)
        if change is None:
            return Material(result=f"想{choice.line}，没弄成")
        return Material(result="；".join(change.lines), done=True,
                        mood={"hunger": change.hunger, "energy": change.energy})

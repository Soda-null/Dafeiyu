"""Look up something she is curious about, on her own time (Wikipedia, the same as `look`)."""

from __future__ import annotations

from fish.brain.leisure.base import Activity, Choice, Kit, Material
from fish.world import Item


class CuriousActivity(Activity):
    key = "curious"

    def offer(self, kit: Kit) -> list[Choice]:
        if kit.searcher is None:
            return []
        return [Choice(self.key, f"查一个自己好奇的东西（{kit.searcher.name}）", arg_hint="想查什么，一个词")]

    def do(self, kit: Kit, choice: Choice, picks: list[int], arg: str) -> Material:
        found = kit.searcher.lookup(arg) if kit.searcher and arg.strip() else None
        if found is None:
            return Material(result=f"想查「{arg.strip()}」，没查到")
        item = Item(found.title, found.url, "", kit.searcher.name, "查东西")
        return Material([(item, found.text)], f"查了「{arg.strip()}」")

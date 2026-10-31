"""The little pier on the lake outside her door (decision 45): she goes and sits there for half
an hour, and when she is back the record says what she saw. What she saw is drawn by lot, the
same for the same hour of the same day (like the goldfish, tank.py), so it is nobody's to make
up. The lot holds nothing the weather could contradict ("阳光晃眼" on a rainy day): the weather
she knows from the chat, and the lake follows it there."""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from fish.cottage.rules import ACTIONS, LAKE_AGAIN_HOURS, LAKE_UNTIL
from fish.cottage.state import Change, Offer, Room

KEYS = ("lake",)
LAKE = ACTIONS["lake"]
BACK = "从湖边码头回来了"
SIGHTS = ("一群野鸭排成一串从码头边游过去", "一只白鹭站在浅水里，半天不动一下", "对岸有个人在钓鱼，一条也没钓上来",
          "码头底下聚着一群小鱼，一跺脚就散了", "一条小木船慢慢划过湖中间", "风吹过来，湖面皱起一片一片的纹",
          "一只翠鸟从水面上擦过去，叼走了什么", "水边的芦苇沙沙响", "湖面很静，对岸的树倒映在水里",
          "几只麻雀落在码头的木桩上吵架")


def sight(at: datetime) -> str:
    """What she sees from the pier in that hour: by lot, the same however often it is asked."""
    return random.Random(f"lake-{at.date().isoformat()}-{at.hour}").choice(SIGHTS)


class LakeMixin:
    """Part of Cottage (room.py): the pier. Uses the room's note."""

    @staticmethod
    def just_at_lake(room: Room, now: datetime) -> bool:
        """Back from the pier less than LAKE_AGAIN_HOURS ago."""
        return any(e["line"].startswith(BACK) and now - datetime.fromisoformat(e["ts"]) < timedelta(hours=LAKE_AGAIN_HOURS)
                   for e in room.events)

    def lake_offers(self, room: Room, now: datetime) -> list[Offer]:
        if (now + timedelta(minutes=LAKE.minutes)).time() > LAKE_UNTIL or now.time() > LAKE_UNTIL:
            return []
        if self.just_at_lake(room, now):
            return []
        return [Offer("lake", "出门到湖边的小码头坐一会儿（就在门口）")]

    def lake_possible(self, room: Room, key: str, now: datetime, arg: str) -> bool:
        return bool(self.lake_offers(room, now))

    @staticmethod
    def _lake_apply(room: Room, key: str, now: datetime, arg: str) -> str:
        room.pending = {"lake": _sight_hour(now)}
        return "出门去湖边码头坐一会儿"

    def _lake_home(self, room: Room, done: datetime, change: Change) -> None:
        """Back from the pier: what she saw goes into the record."""
        seen = sight(datetime.fromisoformat(room.pending["lake"]))
        self.note(room, done, f"{BACK}，坐了半个钟头，看见{seen}", change, routine=room.pending.get("routine", False))
        room.been["lake"] = done.isoformat(timespec="minutes")
        room.pending = {}


def _sight_hour(now: datetime) -> str:
    """The hour she sits there in: the middle of her half hour."""
    return (now + timedelta(minutes=LAKE.minutes // 2)).isoformat(timespec="minutes")

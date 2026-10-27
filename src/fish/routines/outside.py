"""Her place in the world (decision 15): where she lives, today's weather, what is nearby.

Once per fish day (from 07:00): weather. Once ever (or when missing): locate home, list
nearby places (refreshed every 30 days), fetch the neighbourhood map and let her look at
it once, keeping up to three notes. Everything lives in data/home/ and the relationship
ledger; nothing finer than a neighbourhood is stored.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from fish.memory import MemoryStore, Relationship
from fish.routines.nightly import fish_day
from fish.routines.runs import claim_run
from fish.world.http import Fetch, FetchBytes, FetchPost, urllib_fetch, urllib_fetch_bytes, urllib_post
from fish.world.place import (Home, Place, locate, nearby, neighbourhood_map, places_line, weather)

if TYPE_CHECKING:
    from fish.brain.respond import Brain

WEATHER_FROM = time(7, 0)
PLACES_EVERY_DAYS = 30


def home_dir(brain: "Brain") -> Path:
    return brain.album.folder.parent / "home"


def load_home(folder: Path) -> Home | None:
    p = folder / "home.json"
    return Home.from_json(p.read_text(encoding="utf-8")) if p.exists() else None


def load_places(folder: Path) -> list[Place]:
    p = folder / "places.json"
    if not p.exists():
        return []
    return [Place(**d) for d in json.loads(p.read_text(encoding="utf-8"))["places"]]


def run_outside(conn: sqlite3.Connection, now: datetime | None = None, *, brain: "Brain",
                fetch: Fetch = urllib_fetch, fetch_bytes: FetchBytes = urllib_fetch_bytes,
                post: FetchPost = urllib_post) -> dict:
    now = now or datetime.now()
    folder = home_dir(brain)
    folder.mkdir(parents=True, exist_ok=True)
    report: dict = {}

    home = load_home(folder)
    if home is None:
        try:
            home = locate(fetch, at=brain.settings.home_at)
        except Exception as e:  # noqa: BLE001 - no network today: try again next time
            return {"error": f"locate: {e}"}
        (folder / "home.json").write_text(home.to_json(), encoding="utf-8")
        report["home"] = home.line()

    places_file = folder / "places.json"
    stale = (not places_file.exists() or datetime.fromisoformat(
        json.loads(places_file.read_text(encoding="utf-8"))["fetched"]) < now - timedelta(days=PLACES_EVERY_DAYS))
    if stale:
        try:
            places = nearby(home, post)
            places_file.write_text(json.dumps({"fetched": now.isoformat(timespec="seconds"),
                                               "places": [asdict(p) for p in places]}, ensure_ascii=False),
                                   encoding="utf-8")
            report["places"] = len(places)
        except Exception as e:  # noqa: BLE001
            report["places_error"] = str(e)[:80]

    rel = Relationship(conn)
    day = fish_day(now).isoformat()
    if now.time() >= WEATHER_FROM and rel.get("weather_day") != day and claim_run(conn, "weather", day):
        try:
            rel.set("weather_line", weather(home, fetch).line(), now)
            rel.set("weather_day", day, now)
            report["weather"] = rel.get("weather_line")
        except Exception as e:  # noqa: BLE001
            report["weather_error"] = str(e)[:80]

    map_file = folder / "map.png"
    if not map_file.exists():
        try:
            map_file.write_bytes(neighbourhood_map(home, fetch_bytes))
        except Exception as e:  # noqa: BLE001
            report["map_error"] = str(e)[:80]
    if map_file.exists() and rel.get("looked_at_map") is None:
        report["map_notes"] = look_at_map(brain, home, load_places(folder), map_file.read_bytes(), now)
        rel.set("looked_at_map", now.isoformat(timespec="seconds"), now)
    return report


def look_at_map(brain: "Brain", home: Home, places: list[Place], png: bytes, now: datetime) -> int:
    from fish.brain.ask import ask_json
    from fish.messages import data_url

    data = ask_json(brain.llm, "look_map", persona=brain.persona, home=home.line(),
                    places=places_line(places, 25) or "（没查到）", image=data_url(png), temperature=0.9)
    store = MemoryStore(brain.conn)
    n = 0
    for item in (data or {}).get("notes") or []:
        text = str(item.get("text", "")).strip()[:120] if isinstance(item, dict) else ""
        if text:
            try:
                importance = max(5, min(7, int(item.get("importance", 6))))
            except (TypeError, ValueError):
                importance = 6
            store.add("self", text, importance=importance, tags=["家", home.city], now=now)
            n += 1
        if n >= 3:
            break
    return n

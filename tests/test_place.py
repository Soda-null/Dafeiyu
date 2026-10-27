"""Where she lives (decision 15): home at neighbourhood level, weather, nearby places, the map."""

import io
import json
from datetime import datetime
from pathlib import Path

from PIL import Image

from fish.brain import Brain, FakeLLM
from fish.config import Settings
from fish.memory import MemoryStore, Relationship
from fish.routines.outside import load_home, load_places, run_outside
from fish.storage import connect
from fish.world.place import Home, locate, nearby, places_line, weather

T = datetime(2026, 10, 27, 9, 0)
HOME = Home("Springfield", "Ohio", "Downtown", 39.92, -83.81, "America/New_York")


def fake_fetch(url, timeout):
    if "ipinfo" in url:
        return json.dumps({"city": "Springfield", "region": "Ohio", "loc": "39.9242,-83.8088",
                           "timezone": "America/New_York"})
    if "nominatim" in url:
        assert "lat=39.92&lon=-83.81" in url  # only the rounded position ever leaves the box
        return json.dumps({"address": {"quarter": "Downtown", "house_number": "1", "road": "X St"}})
    if "open-meteo" in url:
        return json.dumps({"current": {"temperature_2m": 9.4, "weather_code": 3},
                           "daily": {"temperature_2m_min": [5.2], "temperature_2m_max": [13.8],
                                     "precipitation_probability_max": [60], "weather_code": [61],
                                     "sunset": ["2026-10-27T18:05"]}})
    raise AssertionError(url)


def fake_post(url, form, timeout):
    assert "around:1500,39.92,-83.81" in form["data"]
    return json.dumps({"elements": [
        {"lat": 39.9105, "lon": -83.7988, "tags": {"name": "McDonald's", "amenity": "fast_food", "addr:street": "Green St"}},
        {"center": {"lat": 39.92, "lon": -83.81}, "tags": {"name": "Cafe Kopi", "amenity": "cafe"}},
        {"lat": 39.92, "lon": -83.81, "tags": {"name": "McDonald's", "amenity": "fast_food"}},
        {"lat": 39.92, "lon": -83.81, "tags": {"amenity": "restaurant"}},
    ]})


def fake_tile(url, timeout):
    out = io.BytesIO()
    Image.new("RGB", (256, 256), "lightblue").save(out, "PNG")
    return out.getvalue()


def test_locate_keeps_only_city_and_neighbourhood():
    home = locate(fake_fetch)
    assert home == HOME
    assert home.line() == "你住在 Springfield（Ohio）的 Downtown 一带"
    assert "X St" not in home.to_json()


def test_weather_line():
    w = weather(HOME, fake_fetch)
    assert w.line() == "今天小雨，5 到 14 度，现在 9 度，下雨的可能 60%，18:05 日落"


def test_nearby_places_have_names_kinds_and_minutes_but_no_addresses():
    places = nearby(HOME, fake_post)
    assert [(p.name, p.kind) for p in places] == [("Cafe Kopi", "咖啡馆"), ("McDonald's", "快餐")]
    assert places[1].walk_min > places[0].walk_min >= 1
    assert "Green St" not in places_line(places)


def test_outside_routine_sets_home_weather_places_and_looks_at_the_map_once(tmp_path: Path):
    def respond(messages, json_mode):
        content = messages[-1]["content"]
        assert isinstance(content, list) and content[1]["image_url"]["url"].startswith("data:image/png")
        assert "McDonald's" in content[0]["text"]
        return json.dumps({"notes": [{"text": "我住 Springfield 市中心，走几分钟就有麦当劳。", "importance": 6}]},
                          ensure_ascii=False)

    conn = connect(tmp_path / "fish.db")
    brain = Brain(conn, Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db"),
                  FakeLLM(respond), persona_text="你是大肥鱼。", stickers_dir=tmp_path / "stickers")
    report = run_outside(conn, T, brain=brain, fetch=fake_fetch, fetch_bytes=fake_tile, post=fake_post)
    assert report["places"] == 2 and report["map_notes"] == 1 and "小雨" in report["weather"]
    assert load_home(tmp_path / "home") == HOME and len(load_places(tmp_path / "home")) == 2
    assert Image.open(tmp_path / "home" / "map.png").size == (768, 768)
    assert [m.text for m in MemoryStore(conn).alive("self")] == ["我住 Springfield 市中心，走几分钟就有麦当劳。"]
    again = run_outside(conn, T, brain=brain, fetch=fake_fetch, fetch_bytes=fake_tile, post=fake_post)
    assert again == {}  # same day: no new weather, map already looked at

    brain.llm = FakeLLM([json.dumps({"say": "嗯"})])
    brain.respond("你在哪", now=T)
    system = brain.llm.calls[0][0][0]["content"]
    assert "你住在 Springfield（Ohio）的 Downtown 一带" in system and "McDonald's（快餐，走" in system
    assert "你那儿今天小雨" in system
    assert Relationship(conn).get("weather_day") == "2026-10-27"


def test_home_can_be_set_by_hand_for_a_cloud_server():
    def fetch(url, timeout):
        assert "ipinfo" not in url  # the machine's own location is not asked
        assert "lat=39.92&lon=-83.81" in url
        return json.dumps({"address": {"city": "Springfield", "state": "Ohio", "quarter": "Downtown",
                                       "road": "X St"}})
    assert locate(fetch, at="39.9242,-83.8088") == Home("Springfield", "Ohio", "Downtown", 39.92, -83.81)


def test_her_clock_follows_her_home_when_env_has_no_tz(tmp_path, monkeypatch):
    """No TZ in .env: once she knows where she lives, that place's timezone is her clock."""
    import os
    import time

    from fish.config import load_settings

    orig = os.environ.get("TZ")
    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.setenv("FISH_DB_PATH", str(tmp_path / "fish.db"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "home.json").write_text(HOME.to_json(), encoding="utf-8")
    (tmp_path / ".env").write_text("", encoding="utf-8")
    try:
        load_settings(tmp_path / ".env")
        assert os.environ["TZ"] == "America/New_York"
    finally:  # put the process clock back for the other tests
        if orig is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = orig
        if hasattr(time, "tzset"):
            time.tzset()

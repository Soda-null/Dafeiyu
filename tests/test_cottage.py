"""Her cottage (decision 26): the room is reality, her head is memory. Only he, the rules and
time change the room; what she says changes nothing."""

import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from fish.__main__ import main
from fish.brain import Brain, FakeLLM
from fish.brain.leisure import CottageActivity, Leisure
from fish.config import Settings
from fish.cottage import Cottage, layout
from fish.cottage.rules import in_stock, shop_open
from fish.storage import connect

MON = datetime(2026, 11, 2, 10, 0)  # a Monday: the shop is open
TUE = datetime(2026, 11, 3, 10, 0)  # the shop rests on Tuesdays


def home(tmp_path: Path, now: datetime = MON) -> Cottage:
    c = Cottage(tmp_path / "cottage" / "now.json")
    c.load(now)
    return c


def test_a_new_room_is_a_plain_file_he_can_read(tmp_path):
    c = home(tmp_path)
    data = json.loads(c.path.read_text(encoding="utf-8"))
    assert data["bed"] == "叠好" and [i["name"] for i in data["fridge"]] == ["鸡蛋", "青菜"]
    assert "鸡蛋" in c.path.read_text(encoding="utf-8")  # not \\u escapes
    assert "湖" in layout() and "手机" in layout()


def test_she_sleeps_at_night_and_leaves_the_bed_unmade(tmp_path):
    c = home(tmp_path, datetime(2026, 11, 2, 22, 0))
    c.advance(datetime(2026, 11, 3, 1, 0))
    room = c.load()
    assert room.doing == "睡觉" and room.bed == "在睡"
    assert c.doing_line(room, chatting=True) == "你在睡觉，被他的消息吵醒了"
    c.advance(datetime(2026, 11, 3, 9, 0))
    room = c.load()
    assert room.doing == "" and room.bed == "乱"


def test_a_night_with_nobody_watching_still_unmakes_the_bed(tmp_path):
    c = home(tmp_path, datetime(2026, 11, 2, 22, 0))  # the service was down all night
    c.advance(datetime(2026, 11, 3, 9, 0))
    assert c.load().bed == "乱"


def test_at_mealtime_she_eats_what_there_is_once(tmp_path):
    c = home(tmp_path, datetime(2026, 11, 2, 11, 0))
    rice = c.load().rice
    change = c.advance(datetime(2026, 11, 2, 12, 0))
    room = c.load()
    assert change.lines == ["午饭做了饭，用了青菜、鸡蛋"]  # what goes off first goes first
    assert change.hunger < 0 and room.rice == rice - 1 and room.sink == ["锅"]
    assert [i["name"] for i in room.fridge] == ["鸡蛋"] and room.doing == "做饭"
    assert c.advance(datetime(2026, 11, 2, 13, 0)).lines == []  # one lunch, not two


def test_an_empty_kitchen_means_going_hungry(tmp_path):
    c = home(tmp_path, datetime(2026, 11, 2, 17, 0))
    room = c.load()
    room.fridge, room.rice = [], 0
    c.save(room)
    change = c.advance(datetime(2026, 11, 2, 18, 0))
    assert change.lines == ["到晚饭的点了，家里没东西吃，饿着"] and change.hunger > 0


def test_greens_go_off_and_get_thrown_out(tmp_path):
    c = home(tmp_path, datetime(2026, 11, 2, 9, 0))
    change = c.advance(datetime(2026, 11, 5, 9, 30))
    assert "青菜放坏了，扔了" in change.lines
    assert [i["name"] for i in c.load().fridge] == ["鸡蛋"]


def test_only_what_would_work_is_on_the_menu(tmp_path):
    c = home(tmp_path)
    full = [o.key for o in c.offers(MON, hunger=20, energy=70)]
    assert "cook" not in full and "rice" not in full and "nap" not in full and "shop" in full
    hungry = [o.key for o in c.offers(MON, hunger=80, energy=40)]
    assert {"cook", "rice", "nap"} <= set(hungry)
    assert "shop" not in [o.key for o in c.offers(TUE, hunger=20, energy=70)]
    assert "shop" not in [o.key for o in c.offers(datetime(2026, 11, 2, 18, 55), hunger=20, energy=70)]
    c.act("nap", MON)
    assert c.offers(MON + timedelta(minutes=5), hunger=80, energy=10) == []  # busy napping


def test_the_shop_has_its_hours_and_its_shelves(tmp_path):
    assert shop_open(MON) and not shop_open(TUE) and not shop_open(datetime(2026, 11, 2, 19, 30))
    morning, late = in_stock(MON), in_stock(datetime(2026, 11, 2, 16, 0))
    assert morning[0] == "米" and len(morning) == 7  # six every day and a pumpkin in November, one missing
    assert "青菜" not in late


def test_shopping_fills_the_jar_and_the_fridge_but_not_with_what_is_not_sold(tmp_path):
    c = home(tmp_path)
    room = c.load()
    room.rice = 1
    c.save(room)
    stock = in_stock(MON)
    have = next(g for g in stock if g not in ("米", "鸡蛋", "青菜"))
    change = c.act("shop", MON, f"米、{have}、火锅底料")
    room = c.load()
    assert room.rice == 12 and have in [i["name"] for i in room.fridge]
    assert change.lines == [f"去菜店买了米、{have}（想要的火锅底料没有）"]
    assert c.doing_line(room).startswith("你出门去菜店了")


def test_what_she_says_changes_nothing_in_the_room(tmp_path):
    conn = connect(tmp_path / "fish.db")
    s = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db", cottage=True)
    llm = FakeLLM([json.dumps({"say": "我冰箱满满的，米也一大缸", "mood": "开心"}, ensure_ascii=False)])
    brain = Brain(conn, s, llm, persona_text="你是大肥鱼。")
    brain.relationship.set("weather_line", "晴，8 到 15 度", MON)
    hunger = brain.moods.load().hunger
    brain.respond("你吃饭了吗", now=MON)
    room = brain.cottage.load()
    assert [i["name"] for i in room.fridge] == ["鸡蛋", "青菜"] and room.rice == 6
    system = llm.calls[0][0][0]["content"]
    assert "你住在湖边的小屋" in system and "屋里：冰箱里有鸡蛋" in system
    assert "你说的话变不出东西" in system and "那家离我这儿不远" not in system
    assert brain.moods.load().hunger > hunger  # talking about food is not eating


def test_free_time_at_home_goes_through_the_rules(tmp_path):
    conn = connect(tmp_path / "fish.db")
    s = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db", cottage=True)

    def respond(messages, json_mode):
        content = messages[-1]["content"]
        assert "## 你的小屋" in content and "被子没叠" in content
        n = next(line.split(".")[0] for line in content.splitlines() if line.endswith(". 叠被子"))
        return json.dumps({"pick": int(n), "why": "看着乱"}, ensure_ascii=False)

    brain = Brain(conn, s, FakeLLM(respond), persona_text="你是大肥鱼。")
    room = brain.cottage.load(MON)
    room.bed = "乱"
    brain.cottage.save(room)
    boredom = brain.moods.load().boredom
    brain.leisure = Leisure(brain, [CottageActivity(brain.cottage)], rng=random.Random(0), sources=[])
    moment = brain.free_time(datetime(2026, 11, 2, 15, 0))
    assert moment.choice == "cottage" and moment.result == "叠了被子"
    assert brain.cottage.load().bed == "叠好" and brain.moods.load().boredom < boredom


def test_he_puts_things_in_and_she_sees_it(tmp_path):
    c = home(tmp_path)
    assert c.give("豆腐", MON) == "他往冰箱里放了豆腐"
    c.put_on_sill("一盆薄荷", MON)
    text = c.for_chat(MON + timedelta(minutes=1), hunger=20)
    assert "窗台上：一盆薄荷（他 11-2 送的）" in text and "他往冰箱里放了豆腐" in text


def test_a_file_he_broke_does_not_break_the_chat(tmp_path):
    conn = connect(tmp_path / "fish.db")
    s = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db", cottage=True)
    brain = Brain(conn, s, FakeLLM([json.dumps({"say": "嗯"})]), persona_text="你是大肥鱼。")
    brain.cottage.path.parent.mkdir(parents=True)
    brain.cottage.path.write_text("{ 床: 乱", encoding="utf-8")
    assert brain.respond("在吗", now=MON) == "嗯"


def test_cottage_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FISH_DB_PATH", str(tmp_path / "fish.db"))
    main(["cottage", "put", "米"])
    main(["cottage", "sill", "一盆薄荷"])
    out = capsys.readouterr().out
    assert "他把米缸装满了" in out and "米缸满的" in out and "窗台上：一盆薄荷" in out
    assert date.today().isoformat() in (tmp_path / "cottage" / "now.json").read_text(encoding="utf-8")


def test_the_same_thing_bought_twice_reads_as_one(tmp_path):
    c = home(tmp_path)
    room = c.load()
    room.fridge.append({"name": "鸡蛋", "meals": 3, "bought": "2026-10-30"})
    room.sink = ["锅", "锅", "电饭煲内胆"]
    lines = c.lines(room)
    assert lines["food"].startswith("冰箱里有鸡蛋（够 6 顿）、青菜") and lines["sink"] == "水槽里有两个锅、电饭煲内胆没洗"

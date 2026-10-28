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
    assert change.lines == ["开始做午饭，用青菜、鸡蛋"]  # what goes off first goes first
    assert change.hunger > 0 and room.rice == rice - 1 and room.sink == ["锅"]  # not fed yet
    assert [i["name"] for i in room.fridge] == ["鸡蛋"] and room.doing == "做饭" and not room.ate
    later = c.advance(datetime(2026, 11, 2, 13, 0))  # one lunch, not two; ready at 12:40
    assert later.lines == ["午饭做好了，吃了"] and later.hunger < 0
    room = c.load()
    assert room.ate == "2026-11-02T12:40" and room.doing == "" and not room.pending
    assert c.today(room, datetime(2026, 11, 2, 13, 0)) == ["12:00 开始做午饭，用青菜、鸡蛋", "12:40 午饭做好了，吃了"]


def test_hunger_and_energy_follow_the_day_not_the_chat(tmp_path):
    """Decision 32: in the cottage, talking moves neither; awake hours make her hungry and
    tired, a meal feeds her when it is ready, the night's sleep gives her energy back."""
    from fish.mood import Mood, MoodStore

    before = Mood(energy=60, boredom=20, hunger=30)
    after = MoodStore.after_turn(Mood(**before.__dict__), "吃饭了吗，我在吃面", "吃了", kitchen=True)
    assert (after.energy, after.hunger) == (before.energy, before.hunger)
    assert MoodStore.apply_clock(before, datetime(2026, 11, 2, 18, 0), kitchen=True).hunger == 30
    c = home(tmp_path, datetime(2026, 11, 2, 8, 0))
    change = c.advance(datetime(2026, 11, 2, 10, 0))
    assert change.hunger == 6 and change.energy == -5  # two awake hours
    c.advance(datetime(2026, 11, 2, 22, 0))
    assert c.advance(datetime(2026, 11, 3, 8, 0)).energy == -5  # 22:00–24:00 awake, then asleep


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
    assert brain.moods.load().hunger == hunger  # talking about food is not eating (decision 32)


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


def test_one_life_not_two(tmp_path):
    """With a room, what she did is the room's record; her own notes keep thoughts, and the
    diary reads the room (decision 26, 10-28: merge her invented life with the real one)."""
    from fish.brain.consolidate import Consolidator
    from fish.brain.leisure import NOTHING_AT_HOME, away
    from fish.cottage import invented_act
    from fish.routines import run_nightly

    assert invented_act("煮了碗面") and invented_act("去菜店买了盆花") and invented_act("薄荷养着呢")
    assert not invented_act("想养盆薄荷") and not invented_act("打算明天做饭") and not invented_act("琢磨西游记的结局")

    conn = connect(tmp_path / "fish.db")
    s = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db", cottage=True)
    calls = []

    def respond(messages, json_mode):
        content = messages[-1]["content"]
        calls.append("\n".join(m["content"] for m in messages))  # the system prompt too
        if "你这会儿有空" in content:
            n = next(line.split(".")[0] for line in content.splitlines() if line.endswith(". 叠被子"))
            return json.dumps({"pick": int(n), "why": "乱"}, ensure_ascii=False)
        if "你在写日记" in content:
            return json.dumps({"diary": "叠了被子，想养盆薄荷。", "phase_line": "",
                               "self_notes": [{"text": "煮了碗面", "importance": 4},
                                              {"text": "想养盆薄荷", "importance": 4}]}, ensure_ascii=False)
        return json.dumps({"say": "嗯", "mood": "平静", "notes": [
            {"text": "我今天做了红烧肉", "kind": "self", "about": "日常"},
            {"text": "我想学做红烧肉", "kind": "self", "about": "日常"}]}, ensure_ascii=False)

    brain = Brain(conn, s, FakeLLM(respond), persona_text="你是大肥鱼。")
    room = brain.cottage.load(MON)
    room.bed = "乱"
    brain.cottage.save(room)
    brain.leisure = Leisure(brain, [CottageActivity(brain.cottage)], rng=random.Random(0), sources=[])
    assert NOTHING_AT_HOME in brain.leisure.menu(brain.leisure.kit(MON))
    moment = brain.free_time(datetime(2026, 11, 2, 15, 0))
    assert moment.result == "叠了被子" and not away(moment)

    brain.respond("今天干嘛了", now=datetime(2026, 11, 2, 16, 0))
    system = calls[-1]
    assert "你今天空闲时" not in system  # the bed is in the room's record, not listed twice
    assert "15:00 叠了被子" in system
    mine = [m.text for m in brain.store.alive("self")]
    assert mine == ["我想学做红烧肉"]  # a cooked dish she never cooked is not hers to note

    report = run_nightly(conn, datetime(2026, 11, 3, 3, 30), brain=brain)
    diary_prompt = next(c for c in calls if "你在写日记" in c)
    assert "## 今天在家（屋里真发生的，照这个写）" in diary_prompt and "15:00 叠了被子" in diary_prompt
    assert "今天空闲时你干了什么（一段一行）\n（没记下）" in diary_prompt
    assert report["diary"]
    mine = [m.text for m in brain.store.alive("self")]
    assert "想养盆薄荷" in mine and "煮了碗面" not in mine


def test_what_happened_at_home_is_a_reason_to_text_him(tmp_path):
    from fish.brain.reach import ReachPolicy
    from fish.memory import Relationship

    conn = connect(tmp_path / "fish.db")
    s = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db", cottage=True)
    prompts = []

    def respond(messages, json_mode):
        prompts.append(messages[-1]["content"])
        return json.dumps({"say": "青菜放坏了，心疼", "asked": [], "shared": []}, ensure_ascii=False)

    brain = Brain(conn, s, FakeLLM(respond), persona_text="你是大肥鱼。")
    brain.window.append("user", "在吗", "wechat", None, MON - timedelta(hours=2))
    Relationship(conn).note_active_day(MON - timedelta(hours=2))
    brain.cottage.load(MON - timedelta(days=4))  # the greens are four days old by now
    assert brain.consider_reach_out(MON) is None and prompts == []  # nothing has happened yet
    assert "青菜放坏了，扔了" in brain.cottage.advance(MON).lines
    assert brain.consider_reach_out(MON).text == "青菜放坏了，心疼"
    assert "- 家里的事：10:00 青菜放坏了，扔了" in prompts[-1]
    later = MON + timedelta(hours=4)
    assert ReachPolicy(conn).triggers(later, brain.moods.load(), home=brain.home_lately(later)).home == []


def test_a_meal_on_time_is_not_news_and_her_lone_message_is_not_his(tmp_path):
    """The 10-28 live trial: she texted "饭做好了" after every meal, and a chat where only she spoke
    ("中午做了西红柿炒蛋", no answer) was closed into "他……做了西红柿炒蛋"."""
    conn = connect(tmp_path / "fish.db")
    s = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db", cottage=True)

    def respond(messages, json_mode):
        return json.dumps({"summary": "她说中午做了西红柿炒蛋", "gist": "她做了饭", "importance": 3, "notes": [
            {"text": "他中午做了西红柿炒蛋", "kind": "event", "about": "路过"},
            {"text": "想再买点西红柿", "kind": "self", "about": "日常"}]}, ensure_ascii=False)

    brain = Brain(conn, s, FakeLLM(respond), persona_text="你是大肥鱼。")
    brain.cottage.load(datetime(2026, 11, 2, 11, 0))
    assert brain.cottage.advance(datetime(2026, 11, 2, 12, 0)).lines  # lunch, on time
    assert brain.home_lately(datetime(2026, 11, 2, 12, 0)) == []
    assert brain.cottage.between(datetime(2026, 11, 2), datetime(2026, 11, 3))  # the diary still sees it

    ep = brain.episodes.start("wechat", datetime(2026, 11, 2, 12, 5))
    brain.window.append("fish", "中午做了西红柿炒蛋", "wechat", ep.id, datetime(2026, 11, 2, 12, 5))
    brain.close_episode(brain.episodes.open_episode(), datetime(2026, 11, 2, 16, 0))
    assert [m.text for m in brain.store.alive()] == ["想再买点西红柿"]


def test_life_shows_her_day_without_her_memories(tmp_path, capsys):
    from fish.__main__ import life
    from fish.memory import Diary, MemoryStore, Pastimes

    s = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db", cottage=True)
    conn = connect(s.db_path)
    now = MON.replace(hour=15)
    c = home(tmp_path, MON.replace(hour=7))
    c.give("南瓜", MON.replace(hour=9))
    p = Pastimes(conn)
    p.end_moment(p.begin_moment(MON.replace(hour=14)), "nothing")
    p.end_moment(p.begin_moment(MON.replace(hour=13)), "cottage", result="洗了碗")  # in the room's record already
    Diary(conn).write("2026-11-01", "湖边风大，看了半天鸭子。")
    MemoryStore(conn).add("fact", "他在 Springfield 上学", importance=6, now=now)
    life(conn, s, 3, now=now)
    out = capsys.readouterr().out
    assert "冰箱里有" in out and "南瓜" in out and "09:00 他往冰箱里放了南瓜" in out
    assert "14:00 什么都没干，发了会儿呆" in out and "洗了碗" not in out
    assert "看了半天鸭子" in out and "Springfield" not in out


def test_the_room_says_on_the_bus_what_time_did(tmp_path):
    """Nodes step 4: the room node publishes what a step did; the mood node is the only one that
    changes how she feels; a line written into the room by another program (`fish cottage put`)
    is said on the next step all the same, and only once."""
    from fish.bus import Bus
    from fish.cottage import RoomNode
    from fish.mood import Mood, MoodNode, MoodStore
    from fish.msgs import HomeEvent, MoodMoved, SheAte, SheSlept

    bus, heard = Bus(), []
    for topic in (MoodMoved, SheAte, SheSlept, HomeEvent):
        bus.subscribe(topic, heard.append)
    conn = connect(tmp_path / "fish.db")
    store = MoodStore(conn)
    store.save(Mood(energy=50, boredom=20, hunger=98))
    bus.subscribe(MoodMoved, MoodNode(store).on_moved)
    c = home(tmp_path, datetime(2026, 11, 2, 7, 0))
    room = RoomNode(bus, c)
    room.step(datetime(2026, 11, 2, 7, 0))  # first step: what the record already holds is said once
    heard.clear()
    room.step(datetime(2026, 11, 2, 12, 0))  # woke at 8; lunch starts
    room.step(datetime(2026, 11, 2, 13, 0))  # lunch was ready at 12:40
    kinds = [type(m).__name__ for m in heard]
    assert kinds.count("SheSlept") == 1 and kinds.count("SheAte") == 1 and kinds.count("MoodMoved") == 2
    slept = next(m for m in heard if isinstance(m, SheSlept))
    assert (slept.start.hour, slept.end.hour) == (0, 8)
    assert [m.line for m in heard if isinstance(m, HomeEvent)] == ["开始做午饭，用青菜、鸡蛋", "午饭做好了，吃了"]
    assert all(m.routine for m in heard if isinstance(m, HomeEvent))
    assert 0.0 <= store.load().hunger <= 100.0  # 98 + a morning − a lunch, kept within bounds
    heard.clear()
    Cottage(c.path).give("南瓜", datetime(2026, 11, 2, 13, 5))  # he, from another program
    room.step(datetime(2026, 11, 2, 13, 10))
    room.step(datetime(2026, 11, 2, 13, 20))
    assert [m.line for m in heard if isinstance(m, HomeEvent)] == ["他往冰箱里放了南瓜"]
    assert room.lately(datetime(2026, 11, 2, 13, 30), timedelta(hours=1)) == ["13:05 他往冰箱里放了南瓜"]


def test_mood_moves_only_within_its_bounds():
    from fish.mood import Mood, MoodNode
    from fish.msgs import MoodMoved

    class Store:
        mood = Mood(energy=95, boredom=3, hunger=50)

        def load(self):
            return Mood(**self.mood.__dict__)

        def save(self, m):
            self.mood = m

    s = Store()
    node = MoodNode(s)
    node.on_moved(MoodMoved(MON, energy=+25, boredom=-10))
    node.on_moved(MoodMoved(MON, energy=-5))
    assert (s.mood.energy, s.mood.boredom, s.mood.hunger) == (95, 0, 50)  # 100 then 95; not 115 − 5 = 110 → 100

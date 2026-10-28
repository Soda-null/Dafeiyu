"""Her free time (decision 24): the gate, the menu, doing nothing, reading the news and a
book, the bookmark, the day line, and that a new activity plugs in without touching the loop."""

import json
import random
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from fish.brain import Brain, FakeLLM
from fish.brain.consolidate import Consolidator
from fish.brain.leisure import (NOTHING, Activity, BookActivity, Choice, FeedActivity, Leisure, LeisurePolicy,
                                Material, render_menu)
from fish.config import Settings
from fish.memory import MemoryStore, Pastimes
from fish.storage import connect
from fish.world import Item
from fish.world.days import day_line, solar_term

PERSONA = "你是大肥鱼。"
T = datetime(2026, 11, 7, 14, 0)
RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>少数派</title>
<item><title>鱼缸怎么选</title><link>https://sspai.com/post/1</link><description>圆的还是方的</description></item>
<item><title>第二篇</title><link>https://sspai.com/post/2</link><description></description></item>
</channel></rss>"""
SOURCES = [{"name": "少数派", "kind": "rss", "url": "https://sspai.com/feed", "flavor": "生活"}]
CH1, CH2 = "西遊記/第001回", "西遊記/第002回"
TEXT = {CH1: "混沌未分天地亂" * 600, CH2: "靈根孕育源流出" * 10}  # 4200 and 70 characters


def fetch(url, timeout):
    if url == "https://sspai.com/feed":
        return RSS
    if "sspai.com/post" in url:
        return "<html><body><article><h1>鱼缸怎么选</h1><p>圆的转身费劲，方的好看。</p></article></body></html>"
    if "wikisource" in url and "list=search" in url:
        return json.dumps({"query": {"search": [{"title": "西遊記"}]}})
    if "wikisource" in url and "action=parse" in url:
        links = "".join(f'<a href="/wiki/{c}">{c}</a>' for c in ("%E8%A5%BF%E9%81%8A%E8%A8%98/%E7%AC%AC001%E5%9B%9E",
                                                                  "%E8%A5%BF%E9%81%8A%E8%A8%98/%E7%AC%AC002%E5%9B%9E",
                                                                  "Help:About"))
        return json.dumps({"parse": {"title": "西遊記", "text": links}})
    if "wikisource" in url and "prop=extracts" in url:
        chapter = CH1 if "001" in url else CH2
        return json.dumps({"query": {"pages": [{"extract": TEXT[chapter]}]}})
    raise AssertionError(url)


def number_of(menu_prompt: str, line_start: str) -> int:
    return int(re.search(rf"^(\d+)\. {re.escape(line_start)}", menu_prompt, re.M).group(1))


def she(pick_line: str, items=(), arg="", seen=True, self_note=""):
    """A fake model that picks the menu line starting with `pick_line` and likes what it read."""
    def respond(messages, json_mode):
        content = messages[-1]["content"]
        if "你这会儿有空" in content:
            return json.dumps({"pick": number_of(content, pick_line), "items": list(items), "arg": arg,
                               "why": "想看"}, ensure_ascii=False)
        if "你刚才有空" in content:
            return json.dumps({"seen": [{"n": 0, "text": "孙悟空从石头里蹦出来，比我从蛋里出来还厉害。",
                                         "importance": 4, "tags": ["西游记"]}] if seen else [],
                               "self_notes": [{"text": self_note, "importance": 4}] if self_note else []},
                              ensure_ascii=False)
        raise AssertionError(content[:80])
    return FakeLLM(respond)


def make(tmp_path: Path, llm, activities=None, **settings):
    conn = connect(tmp_path / "fish.db")
    s = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db", **settings)
    brain = Brain(conn, s, llm, persona_text=PERSONA)
    if activities is None:
        activities = [FeedActivity("news", "翻翻新闻", ("rss",), random.Random(0)), BookActivity(fetch)]
    brain.leisure = Leisure(brain, activities, fetch=fetch, sources=SOURCES, rng=random.Random(1))
    return conn, brain


def test_gate_is_about_time_not_about_what_she_should_do(tmp_path):
    conn, brain = make(tmp_path, she("什么都不干"))
    policy = LeisurePolicy(conn, max_per_day=3)
    assert policy.refused(T) is None
    assert policy.refused(datetime(2026, 11, 7, 23, 30)) == "night"
    assert LeisurePolicy(conn, enabled=False).refused(T) == "off"
    brain.window.append("user", "在吗", "wechat", None, T - timedelta(minutes=10))
    assert policy.refused(T) == "talking"
    assert policy.refused(T + timedelta(minutes=40)) is None
    pastimes = Pastimes(conn)
    pastimes.begin_moment(T + timedelta(hours=1))
    assert policy.refused(T + timedelta(hours=2)) == "too soon"
    pastimes.begin_moment(T + timedelta(hours=4))
    pastimes.begin_moment(T + timedelta(hours=7))
    assert policy.refused(T + timedelta(hours=8, minutes=30)) == "enough today"


def test_nothing_is_a_line_like_the_others_and_shuffled(tmp_path):
    conn, brain = make(tmp_path, she("什么都不干"))
    kit = brain.leisure.kit(T)
    firsts = set()
    for seed in range(8):
        brain.leisure.rng = random.Random(seed)
        menu = brain.leisure.menu(kit)
        assert NOTHING in menu
        firsts.add(menu[0].line)
    assert len(firsts) > 1  # no fixed order, so "nothing" is not always last
    text = render_menu([Choice("news", "翻翻新闻", ("【少数派】鱼缸怎么选",)), Choice("book", "开一本书读", arg_hint="书名")])
    assert "1. 翻翻新闻\n   1.1 【少数派】鱼缸怎么选" in text and "（选这个要在 arg 里写：书名）" in text


def test_doing_nothing_is_one_call_and_leaves_no_memory(tmp_path):
    llm = she("什么都不干")
    conn, brain = make(tmp_path, llm)
    energy = brain.moods.load().energy
    moment = brain.free_time(T)
    assert moment.choice == "nothing" and moment.why == "想看"
    assert len(llm.calls) == 1
    prompt = llm.calls[0][0][-1]["content"]
    assert "什么都不做也行。没有哪个更好" in prompt and "翻翻新闻" in prompt and "开一本书读" in prompt
    assert MemoryStore(conn).alive() == []
    assert brain.moods.load().energy > energy
    assert brain.free_time(T + timedelta(minutes=5)) is None  # the gate: three hours apart


def test_reading_the_news_writes_seen_with_the_url(tmp_path):
    conn, brain = make(tmp_path, she("翻翻新闻", items=[1, 2]))
    moment = brain.free_time(T)
    assert moment.choice == "news" and "点开了" in moment.result
    seen = MemoryStore(conn).seen_recently(T, 1)
    assert len(seen) == 1 and seen[0].source.startswith("https://sspai.com/post/")
    assert moment.memories == (seen[0].id,)


def test_a_book_keeps_her_place_and_can_be_put_down(tmp_path):
    conn, brain = make(tmp_path, she("开一本书读", arg="西游记", self_note="想接着看猴子后来怎样"))
    moment = brain.free_time(T)
    assert moment.result == "读了《西遊記》第001回的一段"
    [p] = Pastimes(conn).active(T)
    assert p.title == "西遊記" and p.progress["chapters"] == [CH1, CH2] and p.progress["offset"] == 3000
    assert len([m for m in MemoryStore(conn).alive() if m.kind == "self"]) == 1

    brain.leisure.activities["book"].do(brain.leisure.kit(T), Choice("book", "", payload={"id": p.id}), [], "")
    assert Pastimes(conn).get(p.id).progress == {**p.progress, "i": 1, "offset": 0}  # the rest of 第001回

    brain.llm = she("接着读《西遊記》", self_note="再记一条")
    brain.leisure.brain = brain
    moment = brain.free_time(T + timedelta(hours=4))
    assert moment.result == "读了《西遊記》第002回的一段"
    assert Pastimes(conn).get(p.id).status == "finished"
    assert len([m for m in MemoryStore(conn).alive() if m.kind == "self"]) == 1  # one new thread a day

    conn2, brain2 = make(tmp_path / "b", she("不读《西遊記》了"))
    q = Pastimes(conn2).start("book", "西遊記", "西遊記", {"chapters": [CH1], "i": 0, "offset": 0}, T)
    assert brain2.free_time(T).result == "不读《西遊記》了"
    assert Pastimes(conn2).get(q.id).status == "dropped"


def test_a_bookmark_untouched_for_a_month_is_let_go(tmp_path):
    conn = connect(tmp_path / "fish.db")
    p = Pastimes(conn).start("book", "論語", "論語", {}, T)
    assert Pastimes(conn).active(T + timedelta(days=29))
    assert Pastimes(conn).active(T + timedelta(days=31)) == []
    assert Pastimes(conn).get(p.id).status == "dropped"  # kept, so she can say she once read it


def test_a_book_that_is_not_there_is_one_line_and_no_second_call(tmp_path):
    def nothing_found(url, timeout):
        return json.dumps({"query": {"search": []}})
    llm = she("开一本书读", arg="哈利波特")
    conn, brain = make(tmp_path, llm, activities=[BookActivity(nothing_found)])
    assert brain.free_time(T).result == "想读《哈利波特》，维基文库上没找到"
    assert len(llm.calls) == 1


def test_a_new_activity_plugs_in_without_touching_the_loop(tmp_path):
    class Aquarium(Activity):
        key = "aquarium"

        def offer(self, kit):
            return [Choice(self.key, "看看隔壁鱼缸")]

        def do(self, kit, choice, picks, arg):
            return Material([(Item("隔壁鱼缸", "https://example.org/tank", "", "窗外", "看鱼"), "一条金鱼在吐泡泡")],
                            "看了隔壁鱼缸")

    conn, brain = make(tmp_path, she("看看隔壁鱼缸"), activities=[Aquarium()])
    moment = brain.free_time(T)
    assert moment.choice == "aquarium" and moment.result == "看了隔壁鱼缸"
    assert MemoryStore(conn).seen_recently(T, 1)[0].source == "https://example.org/tank"


def test_what_day_it_is(tmp_path):
    assert solar_term(date(2026, 11, 7)) == "立冬" and solar_term(date(2026, 2, 4)) == "立春"
    assert solar_term(date(2026, 11, 8)) is None
    (tmp_path / "holidays-2026.json").write_text(json.dumps({"days": [
        {"name": "国庆节", "date": "2026-10-01", "isOffDay": True},
        {"name": "国庆节", "date": "2026-10-10", "isOffDay": False}]}), encoding="utf-8")
    assert day_line(date(2026, 10, 1), tmp_path) == "今天国庆节放假。"
    assert day_line(date(2026, 10, 10), tmp_path) == "今天是国庆节的调休，要上班。"
    assert day_line(date(2026, 9, 21), tmp_path) == "离国庆节放假还有 10 天。"
    assert day_line(date(2026, 11, 7), tmp_path) == "今天立冬。"
    assert day_line(date(2026, 11, 9)) == ""


def test_chat_and_diary_see_her_free_time(tmp_path):
    conn, brain = make(tmp_path, she("开一本书读", arg="西游记"))
    brain.free_time(T)
    fields = brain.day_fields(T + timedelta(hours=1))
    assert fields["day_line"] == "今天立冬。"
    assert fields["pastimes_line"].startswith("你在读《西遊記》")
    assert fields["today_line"] == "你今天空闲时：14:00 读了《西遊記》第001回的一段。"
    brain.llm = FakeLLM([json.dumps({"say": "在看西游记", "mood": "平静"})])
    brain.respond("你今天干嘛了", now=T + timedelta(hours=1))
    system = brain.llm.calls[0][0][0]["content"]
    assert "今天立冬。" in system and "你在读《西遊記》" in system and "你今天空闲时" in system

    llm = FakeLLM([json.dumps({"diary": "读了西游记", "self_notes": [], "phase_line": ""})])
    Consolidator(llm, PERSONA).diary("2026-11-07", "平静", [], [], "", leisure=["14:00 读了《西遊記》第001回的一段"])
    assert "14:00 读了《西遊記》第001回的一段" in llm.calls[0][0][-1]["content"]

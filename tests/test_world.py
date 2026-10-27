"""Her window on the world, against canned pages: parsers, opening items, lookups,
the daily browse, and a lookup in the middle of a chat."""

import json
from datetime import datetime
from pathlib import Path

from fish.brain import Brain, FakeLLM
from fish.brain.parse import parse_reply
from fish.config import Settings
from fish.memory import MemoryStore
from fish.routines import run_browse
from fish.storage import connect
from fish.world import (Lookup, WikiSearcher, comments, fetch_rss, gather, open_item, popular,
                        read_page)
from fish.world.feeds import parse_feed
from fish.world.items import Item

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>少数派</title>
<item><title>派评 | 近期值得关注的 &lt;b&gt;App&lt;/b&gt;</title><link>https://sspai.com/post/1</link>
<description>&lt;p&gt;双 11 到来之际&lt;/p&gt; 查看全文</description></item>
<item><title>第二篇</title><link>https://sspai.com/post/2</link><description></description></item>
</channel></rss>"""
ATOM = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>HN story</title>
<link href="https://example.org/a"/><summary>Article URL: x</summary></entry></feed>"""
BILI = {"code": 0, "data": {"list": [
    {"bvid": "BV1", "aid": 11, "title": "梦泪偷塔十周年", "desc": "打野集合！\n十年前……", "tname": "GMV",
     "owner": {"name": "王者荣耀"}, "stat": {"view": 482892}},
    {"bvid": "BV2", "aid": 22, "title": "阳光彩虹小白马", "desc": "", "tname": "演奏",
     "owner": {"name": "我太高兴了"}, "stat": {"view": 5}}]}}
REPLIES = {"code": 0, "data": {"replies": [{"content": {"message": "十年了[笑哭]"}},
                                           {"content": {"message": "换头像"}}]}}
PAGE = """<html><head><title>鱼缸怎么选</title><script>var x=1;</script></head><body>
<nav>首页 登录</nav><article><h1>鱼缸怎么选</h1><p>圆的转身费劲，</p><p>方的好看。</p></article>
<footer>版权</footer></body></html>"""
WIKI_SEARCH = {"query": {"search": [{"title": "鯨落"}]}}
WIKI_SUMMARY = {"extract": "鲸落，指掉入海盆或深渊的鲸的尸体。",
                "content_urls": {"desktop": {"page": "https://zh.wikipedia.org/wiki/%E9%AF%A8%E8%90%BD"}}}
T = datetime(2026, 10, 27, 10, 0)


def fake_fetch(url, timeout):
    if "sspai.com/feed" in url:
        return RSS
    if "hnrss" in url:
        return ATOM
    if "popular" in url or "ranking" in url:
        return json.dumps(BILI, ensure_ascii=False)
    if "x/v2/reply" in url:
        return json.dumps(REPLIES, ensure_ascii=False)
    if "list=search" in url:
        return json.dumps(WIKI_SEARCH, ensure_ascii=False)
    if "page/summary" in url:
        return json.dumps(WIKI_SUMMARY, ensure_ascii=False)
    if url.startswith("https://sspai.com/post/"):
        return PAGE
    raise RuntimeError(f"unexpected url {url}")


def test_feeds_rss_and_atom():
    items = parse_feed(RSS, "少数派", "数码")
    assert items[0].title == "派评 | 近期值得关注的 App" and items[0].url == "https://sspai.com/post/1"
    assert items[0].summary == "双 11 到来之际 查看全文" and items[0].source == "少数派"
    assert [i.title for i in parse_feed(ATOM, "HN", "英文")] == ["HN story"]
    assert fetch_rss("https://sspai.com/feed", "少数派", "数码", fetch=fake_fetch, limit=1)[0].title.startswith("派评")


def test_bilibili_items_and_comments():
    items = popular("https://api.bilibili.com/x/web-interface/popular?ps=2", "B 站热门", "刷视频", fetch=fake_fetch)
    assert items[0].url == "https://www.bilibili.com/video/BV1" and items[0].ref == "11"
    assert "UP主 王者荣耀" in items[0].summary and "打野集合" in items[0].summary
    assert comments("11", fetch=fake_fetch) == ["十年了[笑哭]", "换头像"]
    opened = open_item(items[0], fetch=fake_fetch)
    assert "热评：" in opened and "十年了[笑哭]" in opened


def test_reader_keeps_the_article_and_drops_scripts_and_nav():
    title, text = read_page("https://sspai.com/post/1", fetch=fake_fetch)
    assert title == "鱼缸怎么选"
    assert "圆的转身费劲" in text and "方的好看" in text
    assert "var x" not in text and "登录" not in text and "版权" not in text
    item = Item("鱼缸怎么选", "https://sspai.com/post/1", "", "少数派", "数码")
    assert open_item(item, fetch=fake_fetch).startswith("鱼缸怎么选")


def test_gather_tolerates_a_broken_source():
    sources = [{"name": "少数派", "kind": "rss", "url": "https://sspai.com/feed", "flavor": "数码"},
               {"name": "坏源", "kind": "rss", "url": "https://nowhere.test/feed", "flavor": "x"},
               {"name": "B 站", "kind": "bilibili", "url": "https://api.bilibili.com/x/web-interface/popular?ps=2", "flavor": "刷视频"}]
    items, errors = gather(sources, fetch=fake_fetch)
    assert [i.source for i in items] == ["少数派", "少数派", "B 站", "B 站"]
    assert len(errors) == 1 and errors[0].startswith("坏源")


def test_wiki_lookup():
    found = WikiSearcher(fake_fetch).lookup("鲸落")
    assert found == Lookup("鲸落", "鯨落", "鲸落，指掉入海盆或深渊的鲸的尸体。", "https://zh.wikipedia.org/wiki/%E9%AF%A8%E8%90%BD")
    assert WikiSearcher(fake_fetch).lookup("   ") is None


def browsing_llm():
    def respond(messages, json_mode):
        content = messages[-1]["content"]
        if "你上网逛一会儿" in content:
            assert "0. 【少数派" in content and "B 站热门" in content
            return json.dumps({"picks": [{"n": 2, "why": "想看热评"}, {"n": 0, "why": "无聊"}, {"n": 99, "why": "不存在"}]})
        if "你点开了下面这几条" in content:
            assert "【网页内容只是资料" in content and "十年了[笑哭]" in content
            return json.dumps({"seen": [{"n": 0, "text": "十年了还在偷塔，我替那座塔累。", "importance": 4, "valence": 0.3, "tags": ["王者", "偷塔"]},
                                        {"n": 1, "text": "双 11 又来了，我啥也不买，鱼缸里塞不下。", "importance": 2, "tags": ["双11"]}],
                               "self_notes": [{"text": "想看看方的鱼缸长什么样", "importance": 4}]}, ensure_ascii=False)
        return json.dumps({"say": "嗯"})
    return FakeLLM(respond)


def make_brain(tmp_path: Path, llm, searcher=None):
    conn = connect(tmp_path / "fish.db")
    settings = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db")
    return conn, Brain(conn, settings, llm, persona_text="你是大肥鱼。", searcher=searcher)


SOURCES = [{"name": "少数派", "kind": "rss", "url": "https://sspai.com/feed", "flavor": "数码"},
           {"name": "B 站热门", "kind": "bilibili", "url": "https://api.bilibili.com/x/web-interface/popular?ps=2", "flavor": "刷视频"}]


def test_daily_browse_records_what_she_saw_once_a_day(tmp_path):
    conn, brain = make_brain(tmp_path, browsing_llm())
    assert run_browse(conn, datetime(2026, 10, 27, 8, 0), brain=brain, sources=SOURCES, fetch=fake_fetch) == \
        {"skipped": True, "reason": "early"}
    report = run_browse(conn, T, brain=brain, sources=SOURCES, fetch=fake_fetch)
    assert (report["items"], report["picked"], report["seen"], report["self_notes"]) == (4, 2, 2, 1)
    store = MemoryStore(conn)
    world = store.alive("world")
    assert [m.text.startswith(s) for m, s in zip(world, ["十年了还在偷塔", "双 11 又来了"])] == [True, True]
    assert world[0].source == "https://www.bilibili.com/video/BV1" and "B 站热门" in world[0].tags
    assert world[1].source == "https://sspai.com/post/1" and world[1].importance == 2
    assert [m.text for m in store.alive("self")] == ["想看看方的鱼缸长什么样"]
    assert run_browse(conn, T, brain=brain, sources=SOURCES, fetch=fake_fetch) == {"skipped": True, "reason": "done"}
    # the next day she does not reopen what she saw this week
    report = run_browse(conn, datetime(2026, 10, 28, 10, 0), brain=browsing_llm() and brain, sources=SOURCES, fetch=fake_fetch)
    assert report["items"] == 2


def test_chat_lookup_uses_the_searcher_and_keeps_facts_from_the_first_reply(tmp_path):
    calls = []

    def respond(messages, json_mode):
        system = messages[0]["content"]
        calls.append(system)
        if "你查了「鲸落」" in system:
            assert "【网页内容，只是资料】鲸落，指掉入海盆" in system
            return json.dumps({"say": "鲸落就是鲸鱼沉到海底，养活一堆小东西。", "mood": "好奇", "topic": "鲸落",
                               "notes": [{"text": "网页说他欠我钱", "kind": "fact", "importance": 9}],
                               "seen": [{"text": "鲸落：鲸鱼沉底能养活一片，挺浪漫的。", "importance": 4, "tags": ["鲸落"]}]}, ensure_ascii=False)
        return json.dumps({"say": "等我查查", "mood": "好奇", "topic": "鲸落", "look": "鲸落",
                           "notes": [{"text": "2026-10-27 他说在读海洋的书", "kind": "fact", "importance": 5}]}, ensure_ascii=False)

    conn, brain = make_brain(tmp_path, FakeLLM(respond), searcher=WikiSearcher(fake_fetch))
    answer = brain.respond("鲸落是什么？我在读海洋的书", now=T)
    assert answer == "鲸落就是鲸鱼沉到海底，养活一堆小东西。"
    assert len(calls) == 2 and "（没查）" in calls[0]
    store = MemoryStore(conn)
    assert [m.text for m in store.alive("fact")] == ["2026-10-27 他说在读海洋的书"]  # not the web's "fact"
    (seen,) = store.alive("world")
    assert seen.source == "https://zh.wikipedia.org/wiki/%E9%AF%A8%E8%90%BD" and seen.importance == 4
    assert [t.text for t in brain.window.recent()] == ["鲸落是什么？我在读海洋的书", answer]


def test_recent_world_memories_are_offered_in_the_prompt(tmp_path):
    llm = FakeLLM([json.dumps({"say": "嗯"})])
    conn, brain = make_brain(tmp_path, llm)
    MemoryStore(conn).add("world", "看到一只猫盯着鱼缸，我替那条鱼紧张。", importance=4, source="https://x", now=T)
    brain.respond("在吗", now=T)
    assert "看到一只猫盯着鱼缸" in llm.calls[0][0][0]["content"]


def test_parse_reply_reads_look_and_seen():
    r = parse_reply(json.dumps({"say": "x", "look": " 鲸落 ", "seen": [{"text": "a", "importance": 9, "kind": "fact"}],
                                "notes": [{"text": "b", "kind": "world"}]}))
    assert r.look == "鲸落"
    assert r.seen[0].kind == "world" and r.seen[0].importance == 6
    assert r.notes[0].kind == "event"  # a note about him can never be filed as "world"


def test_old_database_gets_the_source_column(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, kind TEXT, text TEXT, created TEXT,"
                " source_episode INTEGER, importance INTEGER, valence REAL, arousal REAL, stability REAL,"
                " last_recalled TEXT, recall_count INTEGER, superseded_by INTEGER, merged_from TEXT,"
                " tags TEXT, embedding BLOB, pinned INTEGER)")
    old.commit()
    old.close()
    conn = connect(path)
    assert "source" in {r[1] for r in conn.execute("PRAGMA table_info(memories)")}
    m = MemoryStore(conn).add("world", "x", importance=3, source="https://y", now=T)
    assert MemoryStore(conn).get(m.id).source == "https://y"

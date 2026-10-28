"""Memory v3 step 8, turning back to old chats (docs/memory_v3_zh.md §3.2, §12; waiting for the
user's approval, §11 item 1): only when his line asks or names days gone by; at most two pages
of what each chat's level of forgetting left, cut to 160 characters, scrubbed, marked as the gist
and not his words, never the messages; the close keeps each chat's keys to find it by. The model
is a fake; the friend is the scripted 小周; places are Springfield."""

import json
from datetime import datetime, timedelta
from pathlib import Path

from fish.brain import Brain, FakeLLM
from fish.brain.prompt import JSON_REMINDER
from fish.config import Settings
from fish.memory import EpisodeManager, MemoryStore, Window, keys_of, turn_back
from fish.memory.pages import PAGE_CHARS, PAGE_MIN, answered, asked_about, opens, relevance
from fish.storage import connect

PERSONA = "你是大肥鱼。"
FILM_NIGHT = datetime(2027, 1, 8, 23, 10)  # 小周 day 5, a Friday
FILM_ASK = datetime(2027, 1, 9, 23, 41)  # day 6: "昨天那部烂片叫啥来着"
FILM = "他晚上看了部全是广告的烂片《银河快递》。"


def chat_json(say="嗯。", **extra) -> str:
    data = {"say": say, "mood": "平静", "topic": "闲聊", "notes": [], "followups": [], "asked": [],
            "corrections": []}
    data.update(extra)
    return json.dumps(data, ensure_ascii=False)


def make_brain(tmp_path: Path, chat=None, close=None, pages=True):
    def answer(messages, json_mode):
        content = messages[0]["content"]
        if "这次和他的聊天结束了" in content:
            return close(content) if callable(close) else close
        his = messages[-1]["content"].removesuffix(f"\n{JSON_REMINDER}")
        return chat(his) if callable(chat) else (chat or chat_json())

    conn = connect(tmp_path / "fish.db")
    settings = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db", pages=pages)
    llm = FakeLLM(answer)
    return Brain(conn, settings, llm, persona_text=PERSONA), conn, llm


def close_with(summary: str, gist: str = "聊了几句", **extra) -> str:
    return json.dumps({"summary": summary, "gist": gist, "importance": 3, "notes": [], **extra},
                      ensure_ascii=False)


def pages_part(llm: FakeLLM) -> str:
    """The pages section, or "" when she did not look back (the section is then left out)."""
    parts = llm.calls[-1][0][0]["content"].split("## 翻到的以前聊天")
    return parts[1].split("\n## ")[0] if len(parts) > 1 else ""


def add_chat(eps: EpisodeManager, start: datetime, summary: str, gist: str = "", importance: int = 3,
             keys: list[str] | None = None):
    ep = eps.start("terminal", start)
    eps.touch(ep.id, start + timedelta(minutes=10))
    if keys:
        eps.set_keys(ep.id, keys)
    return eps.close(ep.id, summary=summary, gist=gist, importance=importance, valence=0.0,
                     now=start + timedelta(minutes=40))


def test_only_a_line_that_asks_or_names_days_gone_by_opens_the_gate():
    for line in ("昨天那部烂片叫啥来着", "你记得我生日几号不", "我上次期中考考得咋样", "上周五我看的那部烂片",
                 "昨晚吃了麻辣烫，辣死"):
        assert opens(line, FILM_ASK), line
    # today, this week, a bare weekday said in passing (the coming one), what he usually does
    for line in ("今天食堂有糖醋排骨，爽", "这周好累", "周六去 Springfield 看演唱会", "周六早", "我周五一般吃啥",
                 "嗯嗯"):
        assert not opens(line, FILM_ASK), line


def test_the_film_never_noted_comes_back_from_the_summary_of_that_chat(tmp_path):
    # 小周 day 5: the film's name only made it into the chat's summary, no note has it
    brain, conn, llm = make_brain(tmp_path, close=close_with(FILM))
    brain.respond("晚上看了部烂片《银河快递》，全是广告", now=FILM_NIGHT)
    assert MemoryStore(conn).alive() == []
    brain.respond("昨天那部烂片叫啥来着", now=FILM_ASK)  # closes the film chat first
    assert pages_part(llm).strip().endswith(f"- 【那次聊天的大意，昨天 1月8日，不是原话】{FILM}")

    brain.respond("今天好困", now=FILM_ASK + timedelta(minutes=1))  # neither asks nor names a day
    assert pages_part(llm) == ""


def test_with_pages_turned_off_she_does_not_look_back(tmp_path):
    brain, conn, llm = make_brain(tmp_path, close=close_with(FILM), pages=False)
    brain.respond("晚上看了部烂片《银河快递》，全是广告", now=FILM_NIGHT)
    brain.respond("昨天那部烂片叫啥来着", now=FILM_ASK)
    assert "银河快递" not in llm.calls[-1][0][0]["content"]
    assert pages_part(llm) == ""


def test_what_he_typed_is_never_a_page_and_a_page_is_scrubbed_on_the_way_out(tmp_path):
    conn = connect(tmp_path / "fish.db")
    eps = EpisodeManager(conn)
    # his words named the film, but that chat's summary did not: the messages are never looked at
    typed = add_chat(eps, FILM_NIGHT, "聊了几句，他困了")
    Window(conn).append("user", "晚上看了部烂片《银河快递》，门禁 739128", "terminal", typed.id, FILM_NIGHT)
    # an old summary written before the secret filter (step 5) still had the password in it
    old = add_chat(eps, FILM_NIGHT + timedelta(hours=1), "")
    conn.execute("UPDATE episodes SET summary = ? WHERE id = ?",
                 ("他说校园网密码改成 zhou2027 了。后来又说那部烂片《银河快递》全是广告。", old.id))
    conn.commit()
    pages = {p.episode: p.text for p in turn_back(eps.closed(), "昨天那部烂片叫啥来着", FILM_ASK)}
    assert pages == {old.id: "后来又说那部烂片《银河快递》全是广告。", typed.id: "聊了几句，他困了"}


def test_what_is_left_of_a_chat_depends_on_how_old_it_is_and_how_much_it_mattered(tmp_path):
    eps = EpisodeManager(connect(tmp_path / "fish.db"))
    start = datetime(2027, 1, 6, 21, 0)
    add_chat(eps, start, "他和室友去吃了麻辣烫，辣到嘴裂。", gist="他和室友吃了麻辣烫。")
    add_chat(eps, start + timedelta(hours=1), "他晚上和室友聊起家在杭州，有点想家。",
             gist="他想家了。", importance=7)
    ask = "一月初有天晚上我和室友吃的啥，你记得吗"
    soon = turn_back(eps.closed(), ask, datetime(2027, 1, 30, 15, 0))  # 24 days on: the summaries
    assert {(p.text, p.gist_only) for p in soon} >= {("他和室友去吃了麻辣烫，辣到嘴裂。", False)}
    later = turn_back(eps.closed(), ask, datetime(2027, 4, 3, 15, 0))  # day 90
    by_text = {p.text: p.gist_only for p in later}
    assert by_text.get("他和室友吃了麻辣烫。") is True  # not important: only the gist is left
    assert "他和室友去吃了麻辣烫，辣到嘴裂。" not in by_text
    assert by_text.get("他晚上和室友聊起家在杭州，有点想家。") is False  # it mattered: kept


def test_at_most_two_pages_of_at_most_160_characters_with_the_sentence_he_asks_about(tmp_path):
    eps = EpisodeManager(connect(tmp_path / "fish.db"))
    filler = "他说今天的课很无聊，老师一直在念幻灯片，下课后去图书馆坐了一下午。" * 3
    add_chat(eps, FILM_NIGHT, filler + "晚上他看了部烂片《银河快递》，全是广告。")
    for h in (1, 2):
        add_chat(eps, FILM_NIGHT - timedelta(hours=h + 2), f"第{h}次：他晚上看了部烂片，说想睡了。")
    pages = turn_back(eps.closed(), "昨天那部烂片叫啥来着", FILM_ASK)
    assert len(pages) == 2 and all(len(p.text) <= PAGE_CHARS for p in pages)
    assert any(p.text.endswith("晚上他看了部烂片《银河快递》，全是广告。") for p in pages)


def test_the_close_keeps_each_chat_s_keys_and_a_result_finds_its_chat_by_them(tmp_path):
    """小周's midterm: the exam is noted with its tags; days later he tells the score and the close
    hangs it on the exam. That chat now carries the exam's tags, so "期中考考得咋样" a month on
    finds it, which its few words alone would not."""
    exam_text = "他2027-01-13周三有机械设计期中考"

    def chat(his):
        if his == "周三期中考，慌":
            return chat_json("加油", notes=[
                {"text": exam_text, "kind": "event", "about": "日常", "tags": ["机械设计", "期中考"]},
                {"text": "他晚上看了部烂片《银河快递》", "kind": "event", "about": "路过", "tags": ["烂片"]},
                {"text": "他的校园网账号叫 zhou", "kind": "fact", "about": "日常", "tags": ["校园网", "密码"]}])
        return chat_json()

    def close(content):
        if "八十来分" in content:
            exam = next(m for m in store.alive() if m.text == exam_text)
            return close_with("他考完了，说考得还行估计八十来分。", outcomes=[{"id": exam.id, "text": "估计八十来分"}])
        return close_with("他周三要考期中。")

    brain, conn, llm = make_brain(tmp_path, chat=chat, close=close)
    store, eps = MemoryStore(conn), EpisodeManager(conn)
    brain.respond("周三期中考，慌", now=datetime(2027, 1, 11, 18, 30))
    brain.respond("考完了，还行吧，估计八十来分", now=datetime(2027, 1, 14, 9, 0))
    brain.respond("早", now=datetime(2027, 1, 14, 12, 0))  # closes the chat with the score
    first, second = eps.closed()
    assert first.keys == ("机械设计", "期中考", "烂片", "银河快递", "校园网")  # "密码" comes with secrets: no key
    assert set(second.keys) == {"机械设计", "期中考"}  # the event it told the result of

    ask, now = "我上次期中考考得咋样", datetime(2027, 2, 12, 12, 30)  # day 40
    assert relevance(ask, second.summary, ()) < PAGE_MIN <= relevance(ask, second.summary, second.keys)
    assert turn_back(eps.closed(), ask, now)[0].episode == second.id


def test_the_days_he_names_are_not_what_he_asks_about():
    for line, left in (("我上周考的啥来着", "我 考的"), ("上周五我看的那部烂片叫啥来着", "我看的那部烂片"),
                       ("昨晚吃了麻辣烫", "吃了麻辣烫"), ("一月份我看过一部烂片，叫啥", "我看过一部烂片，"),
                       ("我上周搬去哪了你记得不", "我 搬去哪了你"), ("考考你，我生日几号", "，我生日")):
        assert asked_about(line).split() == left.split(), line
    # a summary that only says "上周" again shares nothing with what he asks about
    assert relevance("我上周考的啥来着", "又问我上周五他看的烂片叫什么。", ()) == 0.0


def test_what_she_could_not_answer_is_not_a_page(tmp_path):
    """小周 day 17, "我上周考的啥来着": last week's chats where she failed his quizzes say "上周" too.
    They are not shown ahead of the exam and the score, and nothing shown tells her "他好像没跟我说过"
    (§B5). Here the exam chat left the notes' keys; the score chat left none."""
    eps = EpisodeManager(connect(tmp_path / "fish.db"))
    exam = add_chat(eps, datetime(2027, 1, 11, 12, 5), "他提到周三有机械设计期中考，觉得头大。",
                    keys=["机械设计", "期中考"])
    score = add_chat(eps, datetime(2027, 1, 14, 9, 0), "小周考完试，说考得还行估计八十来分，我问他海边还去不去。")
    add_chat(eps, datetime(2027, 1, 13, 20, 0), "小周问我上周三晚上他吃的什么，我答不上来，说忘了、他好像没跟我说过。")
    add_chat(eps, datetime(2027, 1, 15, 12, 0),
             "小周说今天食堂有糖醋排骨，吃得很爽；又问我上周五他看的烂片叫什么，我没记住，他也没再说。")
    add_chat(eps, datetime(2027, 1, 16, 9, 0), "周末他睡到自然醒，又考我记不记得他最爱吃啥，我答了牛肉面。")
    pages = turn_back(eps.closed(), "我上周考的啥来着", datetime(2027, 1, 20, 20, 10))
    assert [p.episode for p in pages] == [exam.id, score.id]
    # the rest of a chat she failed in is still a page; the sentence she failed in is not
    assert answered("小周说今天食堂有糖醋排骨，吃得很爽；又问我上周五他看的烂片叫什么，我没记住。") == (
        "小周说今天食堂有糖醋排骨，吃得很爽；")
    assert answered("他考我记性，我没接住。") == ""
    for p in turn_back(eps.closed(), "上周我都跟你聊了啥，你还记得吗", datetime(2027, 1, 20, 20, 10), k=9):
        assert not any(w in p.text for w in ("没记住", "答不上", "没跟我说过")), p.text


def test_keys_are_tags_and_names_in_book_title_marks_never_a_secret():
    class M:
        def __init__(self, text, tags):
            self.text, self.tags = text, tags

    assert keys_of([M("他看了《银河快递》和《海》", ["电影", "x"]), M("门锁 739128", ["739128", "电影"])]) == [
        "电影", "银河快递"]  # one-character keys and repeats are left out; so are secrets

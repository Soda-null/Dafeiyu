"""Memory v3 step 2, what a turn searches with (docs/memory_v3_zh.md §3): his line only (hers
too when his is very short), recall by time wired into the chat, her card taking none of the
places of what is recalled and marked where his line touches it, and the card's new order."""

import json
from datetime import datetime, timedelta

from fish.brain import Brain, FakeLLM
from fish.brain.prompt import render_recalled
from fish.config import Settings
from fish.memory import MemoryStore, cue_for, mentioned, recall
from fish.storage import connect

T0 = datetime(2027, 1, 6, 20, 0)
PERSONA = "你是大肥鱼。"


def chat_json(say="嗯。") -> str:
    return json.dumps({"say": say, "mood": "平静", "topic": "闲聊", "notes": [], "followups": [],
                       "asked": [], "corrections": []}, ensure_ascii=False)


def make_brain(tmp_path, say="嗯。"):
    conn = connect(tmp_path / "fish.db")
    settings = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db",
                        window_size=20)
    llm = FakeLLM(lambda messages, json_mode: chat_json(say))
    return Brain(conn, settings, llm, persona_text=PERSONA), conn, llm


def section(system: str, title: str) -> str:
    return system.split(f"## {title}\n", 1)[1].split("\n## ", 1)[0]


# --- the cue -------------------------------------------------------------------------------

def test_the_cue_is_his_line_unless_it_is_too_short_to_mean_anything():
    hers = "你室友又打呼了？"
    assert cue_for("我之前答应过你一件事，是啥", hers) == "我之前答应过你一件事，是啥"
    assert cue_for("对就那个", hers) == f"对就那个 {hers}"  # he is answering her
    assert cue_for("然后呢？", hers) == f"然后呢？ {hers}"
    assert cue_for("我对啥过敏来着", hers) == "我对啥过敏来着"  # 过 of 过敏 is not a particle
    assert cue_for("对就那个", "") == "对就那个"


def test_her_previous_line_no_longer_pushes_his_question_aside(tmp_path):
    brain, conn, llm = make_brain(tmp_path, say="你室友又打呼了？")
    store = MemoryStore(conn)
    promise = store.add("event", "他答应等我放假带我去看海", importance=6, tags=["看海"],
                        now=T0 - timedelta(days=20))
    for i in range(6):
        store.add("event", f"他室友第{i}次打呼，吵得他睡不着", importance=6, tags=["室友"],
                  now=T0 - timedelta(days=1))
    brain.respond("我睡不着", now=T0 - timedelta(minutes=2))  # she answers about his roommate
    brain.respond("我之前答应过你一件事，是啥", now=T0)
    shown = section(llm.calls[-1][0][0]["content"], "这句话让你想起的")
    assert f"[#{promise.id}]" in shown and "室友" not in shown

    brain.respond("对就那个", now=T0 + timedelta(minutes=1))  # too short: her line is the topic
    assert "室友" in section(llm.calls[-1][0][0]["content"], "这句话让你想起的")


def test_a_question_about_last_night_finds_last_night_with_no_word_in_common(tmp_path):
    brain, conn, llm = make_brain(tmp_path)
    store = MemoryStore(conn)
    dinner = store.add("event", "他2027-01-05晚上和室友吃了麻辣烫", importance=3,
                       now=datetime(2027, 1, 5, 22, 0))
    assert recall(store, "昨晚我吃的啥你记得不", T0) == []  # by words alone, nothing
    brain.respond("昨晚我吃的啥你记得不", now=T0)
    assert f"[#{dinner.id}]" in section(llm.calls[-1][0][0]["content"], "这句话让你想起的")


# --- the card --------------------------------------------------------------------------------

def test_the_card_takes_none_of_the_places_and_is_marked_where_he_touches_it(tmp_path):
    brain, conn, llm = make_brain(tmp_path)
    store = MemoryStore(conn)
    allergy = store.note("fact", "他对花生过敏", importance=8, about="本人", tags=["花生", "过敏"],
                         now=T0 - timedelta(days=30))
    sister = store.note("fact", "他有个妹妹叫小雨", importance=8, about="本人", tags=["妹妹", "小雨"],
                        now=T0 - timedelta(days=30))
    dinners = [store.add("event", f"他第{i}次在食堂吃宫保鸡丁", importance=4, tags=["宫保鸡丁"],
                         now=T0 - timedelta(days=i + 1)) for i in range(6)]
    before = store.get(allergy.id).recall_count

    brain.respond("今晚食堂有宫保鸡丁，吃不吃", now=T0)
    system = llm.calls[-1][0][0]["content"]
    card, shown = section(system, "你一直记得的关于他的事"), section(system, "这句话让你想起的")
    assert f"[#{allergy.id}] 他对花生过敏（他这句话提到了）" in card  # peanuts, without saying peanuts
    assert f"[#{sister.id}] 他有个妹妹叫小雨\n" in card + "\n"  # not touched, not marked
    assert all(f"[#{d.id}]" in shown for d in dinners)  # all six places for the rest
    assert f"[#{allergy.id}]" not in shown
    assert store.get(allergy.id).recall_count == before + 1  # touched, as recall would
    assert store.get(sister.id).recall_count == 0


def test_mentioned_is_by_words_and_tags_only(tmp_path):
    store = MemoryStore(connect(tmp_path / "fish.db"))
    home = store.note("fact", "他家在Springfield", importance=8, about="本人", tags=["Springfield"], now=T0)
    milk = store.note("fact", "他乳糖不耐", importance=8, about="本人", now=T0)
    assert mentioned("下周回Springfield", [home, milk]) == [home]
    assert mentioned("来杯拿铁", [home, milk]) == [milk]
    assert mentioned("昨天干嘛了", [home, milk]) == []  # a time word touches nothing


def test_mentioned_reaches_only_allergy_facts_through_the_allergen_table(tmp_path):
    store = MemoryStore(connect(tmp_path / "fish.db"))
    fav = store.note("fact", "他最爱吃花生酱拌面", importance=8, about="本人", now=T0)
    allergy = store.note("fact", "他吃了会起疹子", importance=8, about="本人", tags=["花生过敏"], now=T0)
    assert mentioned("今晚吃宫保鸡丁", [fav, allergy]) == [allergy]  # a peanut he loves is no warning
    joined = store.note("fact", "他不能多吃", importance=8, about="本人", tags=["花", "生过敏"], now=T0)
    assert mentioned("今晚吃宫保鸡丁", [joined]) == []  # keys never match across tag boundaries


def test_a_corrected_card_fact_still_shows_what_she_used_to_think(tmp_path):
    brain, conn, llm = make_brain(tmp_path)
    store = MemoryStore(conn)
    old = store.note("fact", "他住3号楼", importance=8, about="本人", tags=["宿舍"], now=T0 - timedelta(days=10))
    new = store.correct(old.id, "他住7号楼", now=T0 - timedelta(days=5))
    sister = store.note("fact", "他有个妹妹叫小雨", importance=8, about="本人", now=T0 - timedelta(days=5))
    assert {new.id, sister.id} <= {m.id for m in store.profile()}

    brain.respond("今天好累", now=T0)  # not about the dorm: the card shows the correction anyway
    card = section(llm.calls[-1][0][0]["content"], "你一直记得的关于他的事")
    assert f"[#{new.id}] 他住7号楼\n  （你之前记的是：他住3号楼）" in card
    assert card.count("之前记的是") == 1  # the sister was never corrected


def test_the_card_is_pinned_then_safety_then_latest_not_most_stable(tmp_path):
    store = MemoryStore(connect(tmp_path / "fish.db"))
    old = store.note("fact", "他学机械", importance=8, about="本人", arousal=0.9, now=T0 - timedelta(days=60))
    new = store.note("fact", "他迷上了攀岩，一周去三次", importance=8, about="本人", arousal=0.0,
                     now=T0 - timedelta(days=2))
    safe = store.note("fact", "他对花生过敏", importance=8, about="本人", arousal=0.0, now=T0 - timedelta(days=90))
    birthday = store.note("fact", "他生日3月14日", importance=10, about="一辈子", now=T0 - timedelta(days=90))
    assert store.get(old.id).stability > store.get(new.id).stability
    assert [m.id for m in store.profile()] == [birthday.id, safe.id, new.id, old.id]
    again = store.happened_again(old.id, T0)  # it came up again today: it is who he is now
    assert again.last_time == T0.date().isoformat()
    assert [m.id for m in store.profile()] == [birthday.id, safe.id, old.id, new.id]


def test_nothing_recalled_still_means_she_does_not_remember_unless_it_is_on_her_card():
    empty = render_recalled([])
    assert "不记得" in empty and "一直记得" in empty

"""Memory v3 step 1, the confirmed bugs (docs/memory_v3_zh.md §2): merges and corrections keep
what a memory is about, only real corrections show as "what she used to think", a merge never
turns her own doings into his, reflection cannot outdate what it is looking at and can confirm
an old rule in other words, missed follow-ups leave no event, a chat is closed as of its last
message and with all of its turns."""

import json
from datetime import datetime, timedelta

import pytest

from fish.brain import Brain, FakeLLM
from fish.brain.consolidate import Consolidator
from fish.config import Settings
from fish.memory import EpisodeManager, MemoryStore, ProspectiveStore, recall
from fish.memory import stability as st
from fish.routines import run_nightly
from fish.storage import connect

T0 = datetime(2027, 1, 4, 20, 0)
PERSONA = "你是大肥鱼。"


@pytest.fixture
def store(tmp_path):
    return MemoryStore(connect(tmp_path / "fish.db"))


def brain_with(tmp_path, respond, **kw):
    conn = connect(tmp_path / "fish.db")
    settings = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db",
                        window_size=kw.pop("window_size", 20))
    return conn, Brain(conn, settings, FakeLLM(respond), persona_text=PERSONA)


# --- merge and correct carry what a memory is about --------------------------------------

def test_a_merged_fact_about_him_stays_about_him(store):
    a = store.note("fact", "他住在Springfield大学7号楼", importance=5, about="本人", arousal=0.0, now=T0)
    b = store.note("fact", "他宿舍在七号楼四层", importance=5, about="日常", arousal=0.0,
                   now=T0 + timedelta(days=2))
    merged = store.merge([a.id, b.id], "他住Springfield大学7号楼四层", now=T0 + timedelta(days=3))
    assert merged.about == "本人"  # the strongest source; it stays on his card
    assert merged in store.profile()
    assert merged.last_time == "2027-01-06"  # the latest day a source happened
    assert store.get(a.id).why == "merge" and store.get(b.id).why == "merge"


def test_a_merge_of_unconfirmed_rules_is_still_unconfirmed(store):
    a = store.note("insight", "他压力大的时候就聊吃的", importance=7, now=T0)
    b = store.note("insight", "他一紧张就跟我聊吃的", importance=7, now=T0 + timedelta(days=1))
    merged = store.merge([a.id, b.id], "他压力大、一紧张就聊吃的", now=T0 + timedelta(days=2))
    assert merged.unconfirmed and merged.line().endswith("（还说不准）")  # a merge is not evidence
    confirmed = store.note("insight", "他周末喜欢睡懒觉", importance=7, now=T0)
    for day in (1, 2):
        confirmed = store.happened_again(confirmed.id, T0 + timedelta(days=day))
    assert confirmed.about == "本人"
    other = store.note("insight", "他周末爱睡懒觉不起床", importance=7, now=T0 + timedelta(days=3))
    assert store.merge([confirmed.id, other.id], "他周末爱睡懒觉", now=T0 + timedelta(days=4)).about == "本人"


def test_a_merge_keeps_a_pinned_birthday_pinned(store):
    a = store.note("fact", "他生日是3月14日", importance=5, about="一辈子", now=T0)
    b = store.add("fact", "他说3月14号过生日，想吃蛋糕", importance=5, now=T0)
    merged = store.merge([a.id, b.id], "他生日3月14日，想吃蛋糕", now=T0 + timedelta(days=1))
    assert merged.pinned and merged.about == "一辈子" and merged.stability == st.INFINITE


def test_a_correction_keeps_what_it_is_about(store):
    old = store.note("fact", "他学机械设计专业", importance=5, about="本人", arousal=0.0, now=T0)
    new = store.correct(old.id, "他学机械电子专业（他改口了）", now=T0 + timedelta(days=5))
    assert new.about == "本人" and new in store.profile()
    assert new.last_time == "2027-01-09"
    assert store.get(old.id).why == "correct"
    assert store.former(new.id).id == old.id


def test_supersede_needs_a_known_reason(store):
    a = store.add("fact", "x", importance=5, now=T0)
    b = store.add("fact", "y", importance=5, now=T0)
    with pytest.raises(TypeError):
        store.supersede(a.id, b.id)
    with pytest.raises(ValueError):
        store.supersede(a.id, b.id, why="because")


# --- "你之前记的是" only for real corrections ---------------------------------------------

def test_only_a_correction_or_an_update_is_shown_as_what_she_used_to_think(store):
    a = store.add("fact", "他不吃香菜", importance=5, tags=["香菜"], now=T0)
    b = store.add("fact", "他说香菜像肥皂", importance=5, tags=["香菜"], now=T0)
    merged = store.merge([a.id, b.id], "他不吃香菜，说像肥皂", now=T0 + timedelta(days=1))
    assert store.former(merged.id) is None
    hits = recall(store, "香菜", T0 + timedelta(days=2))
    assert hits[0].memory.id == merged.id and hits[0].former is None

    # rules over the cap are pushed out by a new rule: not "what she used to think" either
    for i in range(21):  # rules with no two characters alike, so none is a repeat
        rule = "".join(chr(0x4E00 + 6 * i + k) for k in range(6))
        last = store.note("howto", rule, importance=6, now=T0 + timedelta(minutes=i))
    pushed = [store.get(r[0]) for r in store.conn.execute("SELECT id FROM memories WHERE why = 'cap'")]
    assert len(pushed) == 1 and pushed[0].superseded_by == last.id
    assert store.former(last.id) is None

    old = store.add("fact", "他住3号楼", importance=6, now=T0)
    new = store.add("fact", "他搬到7号楼了", importance=6, now=T0 + timedelta(days=1))
    store.supersede(old.id, new.id, why="update")
    assert store.former(new.id).id == old.id


def test_a_database_from_before_v3_guesses_why(store):
    """Rows superseded before the `why` column: a merge source and a rule pushed out by a rule
    are not shown; a plain replacement still is."""
    a = store.add("fact", "他不吃香菜", importance=5, now=T0)
    b = store.add("fact", "他说香菜像肥皂", importance=5, now=T0)
    merged = store.merge([a.id, b.id], "他不吃香菜，说像肥皂", now=T0)
    r1 = store.add("howto", "他困了就让他去睡", importance=6, now=T0)
    r2 = store.add("howto", "他打游戏时别发长消息", importance=6, now=T0)
    f1 = store.add("fact", "他周五有演示", importance=6, now=T0)
    f2 = store.add("fact", "他周四有演示", importance=6, now=T0)
    store.conn.execute("UPDATE memories SET superseded_by = ?, why = NULL WHERE id = ?", (r2.id, r1.id))
    store.conn.execute("UPDATE memories SET superseded_by = ?, why = NULL WHERE id = ?", (f2.id, f1.id))
    store.conn.execute("UPDATE memories SET why = NULL")
    store.conn.commit()
    assert store.former(merged.id) is None
    assert store.former(r2.id) is None
    assert store.former(f2.id).id == f1.id


# --- a merge does not change whose story it is ---------------------------------------------

def test_a_merge_that_turns_her_own_doings_into_his_is_dropped(store):
    mine_a = store.add("self", "我每晚数鱼缸里的米粒", importance=4, now=T0)
    mine_b = store.add("self", "我数米粒数到三百了", importance=4, now=T0)
    ev_a = store.add("event", "我一直没问成他：演示怎么样", importance=3, now=T0)
    ev_b = store.add("event", "我一直没问成他：演示结果", importance=3, now=T0)
    his_a = store.add("fact", "他不吃香菜", importance=5, now=T0)
    his_b = store.add("fact", "他说香菜像肥皂", importance=5, now=T0)

    def respond(messages, json_mode):
        return json.dumps({"merges": [
            {"ids": [mine_a.id, mine_b.id], "text": "他每晚数米粒，数到三百了"},
            {"ids": [ev_a.id, ev_b.id], "text": "他一直没问成他演示怎么样"},
            {"ids": [his_a.id, his_b.id], "text": "他不吃香菜，说像肥皂"},
        ]}, ensure_ascii=False)

    thinker = Consolidator(FakeLLM(respond), PERSONA)
    merges = thinker.merge_pairs([(mine_b, mine_a), (ev_b, ev_a), (his_b, his_a)])
    assert [set(m.ids) for m in merges] == [{his_a.id, his_b.id}]
    ok = Consolidator(FakeLLM(lambda m, j: json.dumps(
        {"merges": [{"ids": [mine_a.id, mine_b.id], "text": "我每晚数米粒，数到三百了"}]},
        ensure_ascii=False)), PERSONA).merge_pairs([(mine_b, mine_a)])
    assert len(ok) == 1


def test_the_merge_prompt_keeps_whose_story_it_is(tmp_path):
    from fish.brain.prompt import load_template

    text = load_template("merge")
    assert "第三人称" not in text and "原来是谁的事就还写谁" in text


# --- reflection ------------------------------------------------------------------------

def reflect_chats(em: EpisodeManager, day: datetime, label: str) -> None:
    for i in range(5):
        ep = em.start("wechat", day + timedelta(minutes=10 * i))
        em.close(ep.id, summary=label, gist=f"{label}{i}", importance=4, valence=0,
                 now=day + timedelta(minutes=10 * i + 5))


def test_reflection_cannot_outdate_a_rule_from_the_chats_it_reads_and_can_confirm_old_ones(tmp_path):
    prompts: list[str] = []
    answer: dict = {}

    def respond(messages, json_mode):
        text = messages[-1]["content"]
        if "想看出点规律" in text:
            prompts.append(text)
            return json.dumps(answer, ensure_ascii=False)
        return "{}"

    conn, brain = brain_with(tmp_path, respond)
    store = MemoryStore(conn)
    em = EpisodeManager(conn)
    night_one = datetime(2027, 1, 11, 3, 30)
    old_rule = store.note("insight", "他老是半夜才来找我", importance=7, now=T0)  # 01-04
    old_howto = store.note("howto", "他深夜来了就陪着聊两句", importance=7, now=T0)
    reflect_chats(em, datetime(2027, 1, 9, 12, 0), "第一批")
    answer.update(insights=[{"text": "他最近白天也来找我了", "importance": 7}])
    run_nightly(conn, night_one, brain=brain)  # the first look back; it closes 01-10
    new_rule = next(m for m in store.alive("insight") if "白天" in m.text)

    # the next look back reads the chats since 01-10. The daytime rule was written by the last
    # look back and the lunch rule during these chats: both are this evidence, not older than it
    # (the bug: a new rule was called outdated the next time). An old rule seen again in other
    # words is confirmed; the old howto rule is outdated.
    reflect_chats(em, datetime(2027, 1, 12, 12, 0), "第二批")
    chat_rule = store.note("insight", "他中午爱问吃啥", importance=7, now=datetime(2027, 1, 12, 13, 0))
    assert old_howto.id in [m.id for m in store.howto_card()]
    answer.clear()
    answer.update(outdated=[old_howto.id, new_rule.id, chat_rule.id],
                  confirms=[old_rule.id, new_rule.id, chat_rule.id])
    report = run_nightly(conn, datetime(2027, 1, 13, 3, 30), brain=brain)
    prompt = prompts[-1]
    assert f"[#{chat_rule.id}] 他中午爱问吃啥（还说不准）（新记的）" in prompt
    assert f"[#{new_rule.id}] 他最近白天也来找我了（还说不准）（新记的）" in prompt
    assert f"[#{old_rule.id}] 他老是半夜才来找我（还说不准）\n" in prompt
    assert "confirms" in prompt and "相处方式也会过时" in prompt

    assert report["outdated"] == 1 and report["confirmed"] == 1
    assert store.get(old_howto.id).stability == st.WEAKENED_DAYS
    assert old_howto.id not in [m.id for m in store.howto_card()]  # an outdated rule leaves the card
    for rule in (new_rule, chat_rule):  # neither outdated nor confirmed
        assert store.get(rule.id).stability == st.UNCONFIRMED_DAYS and store.get(rule.id).times == 1
    assert store.get(old_rule.id).times == 2


def test_the_first_look_back_can_outdate_what_came_before_its_chats(tmp_path):
    def respond(messages, json_mode):
        if "想看出点规律" in messages[-1]["content"]:
            return json.dumps({"outdated": [early.id, during.id]})
        return "{}"

    conn, brain = brain_with(tmp_path, respond)
    store = MemoryStore(conn)
    early = store.note("insight", "他老是半夜才来找我", importance=7, now=T0)
    reflect_chats(EpisodeManager(conn), datetime(2027, 1, 6, 12, 0), "一批")
    during = store.note("insight", "他最近白天来", importance=7, now=datetime(2027, 1, 6, 12, 30))
    report = run_nightly(conn, datetime(2027, 1, 8, 3, 30), brain=brain)
    assert report["outdated"] == 1
    assert store.get(early.id).stability == st.WEAKENED_DAYS
    assert store.get(during.id).stability == st.UNCONFIRMED_DAYS


# --- follow-ups and closing a chat -----------------------------------------------------

def test_a_follow_up_she_never_asked_leaves_no_event(tmp_path):
    conn, _ = brain_with(tmp_path, lambda m, j: "{}")
    ps = ProspectiveStore(conn)
    ps.add("问问他3月14号生日想怎么过", "2027-03-10", now=T0)
    report = run_nightly(conn, datetime(2027, 3, 13, 3, 30))
    assert report["expired"] == 1 and MemoryStore(conn).alive() == []
    assert ps.get(1).status == "expired"


def test_a_chat_is_closed_as_of_its_last_message_and_with_all_its_turns(tmp_path):
    close_prompts: list[str] = []

    def respond(messages, json_mode):
        content = messages[0]["content"]
        if "这次和他的聊天结束了" in content:
            close_prompts.append(content)
            return json.dumps({"summary": "聊了演示", "gist": "他紧张", "importance": 6, "valence": -0.2,
                               "notes": [{"text": "他周五有演示", "kind": "event", "about": "日常"}],
                               "followups": [{"text": "问他演示怎么样", "due": "2027-01-08"}]},
                              ensure_ascii=False)
        if "想看出点规律" in content or "看起来很像" in content:
            return "{}"
        return json.dumps({"say": "嗯"}, ensure_ascii=False)

    conn, brain = brain_with(tmp_path, respond)
    for i in range(8):  # 16 turns: more than the 12 the close used to see
        brain.respond(f"第{i}句", now=T0 + timedelta(minutes=i))
    run_nightly(conn, datetime(2027, 1, 5, 3, 30))  # no brain: the chat stays open
    report = run_nightly(conn, datetime(2027, 1, 6, 3, 30), brain=brain)  # closes it, hours later
    assert report["closed"] == 1
    assert "第0句" in close_prompts[0] and "第7句" in close_prompts[0]
    (note,) = MemoryStore(conn).alive("event")
    assert note.created == "2027-01-04T20:07:00" and note.last_time == "2027-01-04"
    (f,) = ProspectiveStore(conn).open()
    assert f.created == "2027-01-04T20:07:00"

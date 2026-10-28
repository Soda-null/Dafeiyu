"""Memory v3 step 4, promises and the nickname (docs/memory_v3_zh.md §2.1, §3): found by fixed
words in notes heard from him (D1/D2), "for now" no longer demoting what lasts (D3), a repeat that
says more raising the old memory (D4), the block of open promises with a star on the one his line
touches, follow-ups about a promise that never run out, and promises settled at the close.
The friends are the scripted ones (小周, 小林); places are Springfield."""

import json
from datetime import datetime, timedelta

from fish.brain import Brain, FakeLLM
from fish.brain.prompt import render_pacts
from fish.config import Settings
from fish.memory import MemoryStore, ProspectiveStore, triggered
from fish.memory.pacts import nickname, promise
from fish.routines.nightly import _update_groups
from fish.storage import connect

T0 = datetime(2027, 1, 9, 23, 42)  # 小周 day 5, the night of the promise
PERSONA = "你是大肥鱼。"
SEA = "他2027-01-09说期末考完要去海边玩，答应拍海的照片给大肥鱼看。"  # 小周 #17, filed as 日常
POEM = "我答应他：等他驾照拿到那天，我给他写首打油诗庆祝"  # 小林 day 12, her promise


def chat_json(say="嗯。", notes=(), followups=()) -> str:
    return json.dumps({"say": say, "mood": "平静", "topic": "闲聊", "notes": list(notes),
                       "followups": list(followups), "asked": [], "corrections": []}, ensure_ascii=False)


def make_brain(tmp_path, answer=None):
    conn = connect(tmp_path / "fish.db")
    settings = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db",
                        window_size=20)
    llm = FakeLLM(answer or (lambda messages, json_mode: chat_json()))
    return Brain(conn, settings, llm, persona_text=PERSONA), conn, llm


def section(system: str, title: str) -> str:
    return system.split(f"## {title}", 1)[1].split("\n## ", 1)[0]


def store_of(tmp_path) -> MemoryStore:
    return MemoryStore(connect(tmp_path / "fish.db"))


# --- D1: promises ----------------------------------------------------------------------------

def test_a_promise_heard_in_chat_is_pinned_and_open_however_it_was_filed(tmp_path):
    store = store_of(tmp_path)
    sea = store.note("event", SEA, importance=5, about="日常", tags=["海边", "期末"], now=T0, heard="chat")
    assert (sea.about, sea.pinned, sea.pact, sea.pact_state) == ("一辈子", True, "him", "open")
    poem = store.note("self", POEM, importance=5, about="日常", now=T0, heard="chat")
    assert (poem.pact, poem.pinned) == ("her", True)
    cherry = store.note("fact", "他和我约好明年春天一起去Springfield看樱花", importance=5, about="日常",
                        now=T0, heard="close")
    assert cherry.pact == "both"
    # without a promise word: "等…考完…给你拍" is one too
    assert promise("他说等期末考完他去海边玩，给我拍海的照片", "event") == "him"
    assert promise("他和我说好了周末一起看电影", "event") == "him"  # 和我说好 is to her
    assert [p.id for p in store.pacts()] == [cherry.id, poem.id, sea.id]


def test_a_promise_to_someone_else_or_written_by_her_alone_is_not_a_pact(tmp_path):
    store = store_of(tmp_path)
    for text in ("他答应室友周末一起去爬山", "他跟室友说好周六打球", "他答应他妈过年回家",
                 "他在等室友，给我发了个消息", "他保证下次不熬夜了",
                 # waiting is not a condition, and what he sent her is not something to come
                 "他等公交等了好久，给我发了个哭脸", "他等外卖等到十点，结果给我发了张照片吐槽",
                 # 跟我说 is him telling her; a third person before the promise word is somebody else's
                 "他2027-01-20跟我说他和导师约好了下周见面", "他说他跟导师保证了下周交初稿，给我吐槽了半天",
                 "他和室友约好周末去爬山，回来给我看照片"):
        m = store.note("event", text, importance=5, about="日常", now=T0, heard="chat")
        assert m.pact is None and not m.pinned, text
    # her own plan from browsing or the night: never a pact, though the words are a promise's
    plan = "我答应上午给他带点好玩的事，得早点上网逛逛"
    assert store.note("self", plan, importance=4, now=T0).pact is None
    assert promise(plan, "self") == "her"  # it is the source, not the words, that keeps it out
    # a rule the night drew is not one either
    assert promise("他答应过我的事要记着提醒他", "insight") is None
    assert store.pacts() == []


# --- D2: the nickname ----------------------------------------------------------------------------

def test_the_nickname_he_gave_her_is_a_pinned_fact_on_her_card(tmp_path):
    store = store_of(tmp_path)
    m = store.note("howto", "他给我起的外号是胖鱼", importance=5, now=T0, heard="chat")
    assert (m.kind, m.about, m.pinned, m.pact, m.pact_state) == ("fact", "一辈子", True, "both", None)
    assert [p.id for p in store.profile()] == [m.id] and store.pacts() == []
    assert nickname("他管我叫阿肥") and nickname("他喊我“阿肥”")


def test_what_only_looks_like_a_nickname_stays_what_it_was(tmp_path):
    store = store_of(tmp_path)
    for text in ("他叫我别熬夜", "他喊我早点睡", "他室友的外号叫大头，我笑死了", "他的外号叫小周周"):
        assert not nickname(text), text
        m = store.note("event", text, importance=5, about="日常", now=T0, heard="chat")
        assert m.pact is None and m.kind == "event", text
    # the night's rule about it is not heard from him: it stays an unconfirmed rule (小周 #3)
    rule = store.note("insight", "他喜欢给人起外号，认识没多久就叫我胖鱼。", importance=5, now=T0)
    assert (rule.kind, rule.about, rule.pact) == ("insight", "待印证", None)


# --- D3: "for now" no longer demotes what lasts ---------------------------------------------

def test_today_in_a_note_about_his_family_or_home_does_not_make_it_a_passing_thing(tmp_path):
    store = store_of(tmp_path)
    lasting = ("他说妹妹今天打电话来，她叫小雨，读高二", "他今天告诉我他家在Springfield",
               "他说上次吃错花生肿了一脸，这次让我以后提醒他")
    passing = ("他这几天嗓子哑了", "他最近在减肥", "他今天心情不好")
    for text in lasting:
        assert store.note("fact", text, importance=5, about="本人", now=T0).about == "本人", text
    for text in passing:
        assert store.note("fact", text, importance=5, about="本人", now=T0).about == "日常", text


# --- D4: a repeat can raise the old memory ---------------------------------------------------

def test_a_promise_told_again_raises_the_old_plan_to_a_pact(tmp_path):
    store = store_of(tmp_path)
    plan = store.note("event", "他说期末考完要去海边玩，拍海的照片", importance=5, about="日常",
                      tags=["海边"], now=T0, heard="chat")
    assert plan.pact is None and not plan.pinned
    again = store.note("event", "他说期末考完要去海边玩，答应拍海的照片给我看", importance=5,
                       about="日常", now=T0 + timedelta(days=2), heard="chat")
    assert again.id == plan.id and len(store.alive()) == 1
    assert (again.about, again.pinned, again.pact, again.pact_state) == ("一辈子", True, "him", "open")
    # and never down: the same words filed as 路过 leave it as it is
    once_more = store.note("event", "他说期末考完要去海边玩，答应拍海的照片给我看", importance=3,
                           about="路过", now=T0 + timedelta(days=3))
    assert (once_more.about, once_more.pinned) == ("一辈子", True)


def test_a_repeat_with_a_new_number_or_title_is_written_as_news(tmp_path):
    store = store_of(tmp_path)
    exam = store.note("event", "他期中考完了", importance=5, about="日常", now=T0)
    score = store.note("event", "他期中考完了，考了82分", importance=5, about="日常", now=T0)
    film = store.note("event", "他和室友看了部烂片《银河快递》", importance=3, about="路过", now=T0)
    assert score.id != exam.id and film.id not in (exam.id, score.id)
    assert store.note("event", "他期中考完了，考了82分", importance=5, about="日常", now=T0).id == score.id


# --- the block of open promises and its star ------------------------------------------------

def test_the_open_promises_are_always_in_front_of_her_and_his_trigger_stars_one(tmp_path):
    brain, conn, llm = make_brain(tmp_path)
    store = MemoryStore(conn)
    poem = store.note("self", POEM, importance=5, tags=["驾照", "打油诗"], now=T0, heard="chat")
    sea = store.note("event", SEA, importance=5, tags=["海边", "期末"], now=T0 + timedelta(hours=1),
                     heard="chat")
    brain.respond("今天好累", now=T0 + timedelta(days=30))
    system = llm.calls[-1][0][0]["content"]
    block = section(system, "你们之间的约定")
    assert f"[#{sea.id}] 他答应过你：{SEA}" in block and f"[#{poem.id}] 你答应过他：{POEM}" in block
    assert "★" not in block
    assert POEM not in section(system, "你一直记得的关于他的事")
    assert POEM not in section(system, "这句话让你想起的")

    brain.respond("驾照拿到了！！！", now=T0 + timedelta(days=34))
    block = section(llm.calls[-1][0][0]["content"], "你们之间的约定")
    assert block.strip().splitlines()[1] == f"- ★[#{poem.id}] 他刚说到「驾照」——你答应过他：{POEM}"
    assert triggered("驾照拿到了", store.pacts()) == {poem.id: "驾照"}
    assert render_pacts([]) == "（没有）"


# --- follow-ups about a promise, and settling it at the close ------------------------------

def test_a_follow_up_about_an_open_promise_is_never_let_go(tmp_path):
    brain, conn, _ = make_brain(tmp_path)
    store, later = MemoryStore(conn), ProspectiveStore(conn)
    sea = store.note("event", SEA, importance=5, tags=["海边", "期末"], now=T0, heard="chat")
    brain.add_followup("期末考完去海边了吗", "2027-01-20", T0)
    brain.add_followup("问他感冒好了没", "2027-01-11", T0)
    # a shared tag (期末) alone does not tie the exam's result to the promise of the sea
    brain.add_followup("问问他期末考得怎么样", "2027-01-15", T0)
    sea_ask, cold, exam = sorted(later.open(), key=lambda f: f.id)
    assert sea_ask.source_memory == sea.id and cold.source_memory is None and exam.source_memory is None
    gone = later.expire(T0 + timedelta(days=60))
    assert {f.id for f in gone} == {cold.id, exam.id} and [f.id for f in later.open()] == [sea_ask.id]
    store.settle(sea.id, "kept", T0 + timedelta(days=61))  # kept: the question can go now
    assert [f.id for f in later.expire(T0 + timedelta(days=62))] == [sea_ask.id]


def test_the_close_settles_only_a_promise_it_was_shown(tmp_path):
    def answer(messages, json_mode):
        if "这次和他的聊天结束了" not in messages[0]["content"]:
            return chat_json()
        return json.dumps({"summary": "他从海边回来了", "gist": "他拍了海", "importance": 6, "valence": 0.6,
                           "notes": [{"text": "他说等论文交了，带我去Springfield的海洋馆", "kind": "event",
                                      "about": "日常", "tags": ["海洋馆"]}],
                           "followups": [],
                           "pact_done": [{"id": sea.id, "state": "kept"}, {"id": cold.id, "state": "dropped"},
                                         {"id": 999, "state": "kept"}, {"id": poem.id, "state": "maybe"}]},
                          ensure_ascii=False)

    brain, conn, llm = make_brain(tmp_path, answer)
    store = MemoryStore(conn)
    sea = store.note("event", SEA, importance=5, tags=["海边"], now=T0, heard="chat")
    poem = store.note("self", POEM, importance=5, tags=["驾照"], now=T0, heard="chat")
    cold = store.note("event", "他感冒了", importance=4, about="日常", now=T0)
    brain.respond("拍到海了，给你看", now=T0 + timedelta(days=20))
    brain.respond("我回来了", now=T0 + timedelta(days=20, hours=3))  # closes the first chat
    close_prompt = next(c[0][0]["content"] for c in llm.calls if "这次和他的聊天结束了" in c[0][0]["content"])
    assert f"[#{sea.id}] 他答应过你" in close_prompt.split("还开着的约定：", 1)[1]
    assert store.get(sea.id).pact_state == "kept" and store.get(poem.id).pact_state == "open"
    assert store.get(cold.id).pact is None
    aquarium = next(m for m in store.alive() if "海洋馆" in m.text)  # a close note is heard from him
    assert (aquarium.pact, aquarium.pact_state) == ("him", "open")
    assert [p.id for p in store.pacts()] == [aquarium.id, poem.id]
    # kept: off the block and never on her card; pinned, it comes back when he brings it up
    assert sea.id not in {m.id for m in store.profile()}
    brain.respond("还记得我拍的海边吗", now=T0 + timedelta(days=20, hours=3, minutes=5))
    # he asks her to remember: kept promises are in the promise block, in front of her (10-28)
    shown = section(llm.calls[-1][0][0]["content"], "你们之间的约定")
    assert f"{SEA}（兑现了）" in shown


def test_kept_promises_never_crowd_his_allergy_off_her_card(tmp_path):
    store = store_of(tmp_path)
    nut = store.note("fact", "他对花生过敏", importance=5, about="本人", now=T0)
    name = store.note("fact", "他给我起的外号是胖鱼", importance=5, now=T0, heard="chat")
    kept = [store.note("event", f"他答应我第{i}周去Springfield给我拍照片", importance=5, now=T0, heard="chat")
            for i in range(1, 13)]
    assert len({m.id for m in kept}) == 12 and all(m.pact == "him" for m in kept)
    for m in kept:
        store.settle(m.id, "kept", T0 + timedelta(days=1))
    assert [m.id for m in store.profile()] == [name.id, nut.id] and store.pacts() == []


# --- a pact survives what happens to it at night ---------------------------------------------

def test_a_pact_carries_through_merge_and_correction_and_no_update_replaces_it(tmp_path):
    store = store_of(tmp_path)
    sea = store.note("event", SEA, importance=5, tags=["海边"], now=T0, heard="chat")
    other = store.add("event", "他又说起考完去海边拍照片给我看", importance=5, now=T0 + timedelta(days=1))
    merged = store.merge([sea.id, other.id], "他答应期末考完去海边，拍海的照片给我看", now=T0 + timedelta(days=2))
    assert (merged.pact, merged.pact_state, merged.pinned) == ("him", "open", True)
    fixed = store.correct(merged.id, "他答应寒假去海边，拍海的照片给我看", now=T0 + timedelta(days=3))
    assert (fixed.pact, fixed.pact_state) == ("him", "open")

    promised = store.note("fact", "他答应我每周给我讲一个冷笑话", importance=5, now=T0, heard="chat")
    newer = store.add("fact", "他说每周给我讲一个冷笑话太难了", importance=5, now=T0 + timedelta(days=4))
    groups = _update_groups([newer], store.alive(), set())
    assert all(promised.id not in [o.id for o in olds] for _, olds in groups)


def test_his_promise_to_her_is_his_even_when_it_says_wo_baozheng():
    """10-28 checkups: "他跟我保证5月底之前把烟戒了" was filed as hers, kept, out of sight."""
    from fish.memory.pacts import HERS
    assert not HERS.search("他跟我保证5月底之前把烟戒了，让我监督他")
    assert not HERS.search("他和我承诺下次带我去看海")
    assert HERS.search("我答应他每天提醒他喝水") and HERS.search("他让我答应：他说要辞职我先拦着")

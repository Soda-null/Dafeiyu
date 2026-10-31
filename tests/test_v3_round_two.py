"""Memory v3, what the second paid checkups showed (docs/memory_v3_zh.md §14): a reply that went
on past her line (a made-up turn of his, the fields written out, a JSON object) and the plain-text
second try that let it through; promises lost with an unparsed reply, filed as insights, hidden once
kept, starred only by tags; time words read weeks later as if said today; time cues of a part of a
month or a holiday; notes that wrote her own guesses down as his; merges that could not tell which
of two notes is newer. The model is a fake and everything in here is made up (Springfield)."""

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from fish.brain import Brain, Consolidator, FakeLLM
from fish.brain.parse import clean_say, cut_say, parse_reply, parse_retry
from fish.brain.prompt import PROMPTS_DIR, render_pacts
from fish.brain.reach import Reacher, Triggers
from fish.urges import HIM, Urge
from fish.brain.respond import FALLBACK_SAY, PLAIN_REMINDER
from fish.config import Settings
from fish.memory import MemoryStore, asks_pact, asks_recall, echoes_her, his_line, triggered
from fish.memory.pacts import condition, promise
from fish.memory.when import absolute, day_of, spoken, window
from fish.mood import Mood
from fish.storage import connect

T0 = datetime(2027, 1, 25, 20, 0)  # a Monday
PERSONA = "你是大肥鱼。"


def chat_json(say="嗯。", notes=(), **extra) -> str:
    data = {"say": say, "mood": "平静", "topic": "闲聊", "notes": list(notes), "followups": [],
            "asked": [], "corrections": []}
    data.update(extra)
    return json.dumps(data, ensure_ascii=False)


def make_brain(tmp_path: Path, answer=None, close=None):
    def default(messages, json_mode):
        if "这次和他的聊天结束了" in messages[0]["content"]:
            return close(messages[0]["content"]) if callable(close) else (close or json.dumps(
                {"summary": "聊了几句", "gist": "聊了几句", "notes": []}, ensure_ascii=False))
        return answer(messages, json_mode) if answer else chat_json()

    conn = connect(tmp_path / "fish.db")
    settings = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db", window_size=20)
    llm = FakeLLM(default)
    return Brain(conn, settings, llm, persona_text=PERSONA), conn, llm


def section(system: str, title: str) -> str:
    return system.split(f"## {title}", 1)[1].split("\n## ", 1)[0]


# --- what reaches him as her words -------------------------------------------------------------

@pytest.mark.parametrize("raw, said", [
    ("好啊\n\nuser嗯 你猜\n\nsystem{\"say\": \"…\"}", "好啊"),
    ("行\n\nmood：平静", "行"),
    ("嗯\nmood: 好奇\ntopic: 吃饭\nnotes: []", "嗯"),
    ("去吧\n\nsay: 去吧\nmood: 平静", "去吧"),
    ("好\n他：那明天见", "好"),
    ("好\n你：嗯", "好"),
    ("好\n<｜User｜>周末去放风筝吗", "好"),
    ("对啊\n\n{\"say\": \"对啊\"}", "对啊"),
    ("say: 早点睡", "早点睡"),
    ("你：早点睡", "早点睡"),
    ("哈哈哈{\"say\": \"哈\"}", "哈哈哈"),
])
def test_what_she_wrote_past_her_line_is_cut(raw, said):
    assert clean_say(raw) == said


@pytest.mark.parametrize("text", [
    "今天好冷\n你那边下雪没", "他说：明天去 Springfield 放风筝", "心情还行吧", "user 是什么意思啊",
])
def test_an_ordinary_reply_is_left_as_it_is(text):
    assert clean_say(text) == text


def test_a_sticker_placeholder_is_still_split_out_after_cleaning():
    r = parse_reply(chat_json(say="笑死 [sticker #2]\n\nmood：开心"))
    assert (r.say, r.sticker) == ("笑死", 2)


def test_the_fields_written_into_say_are_cut_and_the_real_ones_kept():
    r = parse_reply('{"say": "行\\n\\nmood：平静", "mood": "平静"}')
    assert (r.say, r.mood, r.parsed) == ("行", "平静", True)


def test_a_say_that_went_on_into_a_made_up_turn_of_his_records_nothing():
    """What she noted may be what "he" said in the turn she made up."""
    r = parse_reply(chat_json(say="那你猜猜\nuser 大概1500吧", notes=[{"text": "他房租1500", "kind": "fact"}],
                              corrections=[{"old_id": 3, "text": "他房租1500"}]))
    assert r.say == "那你猜猜" and r.notes == [] and r.corrections == []
    assert cut_say("那你猜猜\nuser 大概1500吧") == ("那你猜猜", True)
    assert cut_say("行\n\nmood：平静") == ("行", False)


def test_the_plain_text_retry_keeps_a_json_it_wrote_after_her_line_but_not_after_a_made_up_turn():
    note = {"text": "他周末想去湖边放风筝", "kind": "event", "about": "日常"}
    kept = parse_retry("好呀，带上我\n\n" + chat_json(say="好呀，带上我", notes=[note]))
    assert kept.say == "好呀，带上我" and [n.text for n in kept.notes] == [note["text"]]
    lost = parse_retry("好呀\n\nuser 那就说定了\n\nsystem" + chat_json(say="说定了", notes=[note]))
    assert lost.say == "好呀" and lost.notes == [] and not lost.parsed


def test_when_the_json_reply_gives_nothing_the_plain_retry_is_cleaned_before_it_is_kept(tmp_path):
    """The JSON reply comes back empty; asked again in plain text the model writes her line and a
    turn of his. He never sees that turn, it is not stored as hers (the next prompt would show it as
    her own words), and nothing is noted from it."""
    def answer(messages, json_mode):
        if json_mode:
            return ""
        return "你自己猜嘛\n\nuser 好像是3600\n\nassistant 对，3600"

    brain, conn, llm = make_brain(tmp_path, answer)
    assert brain.respond("我房租多少你记得不", now=T0) == "你自己猜嘛"
    assert [j for _, j in llm.calls[:3]] == [True, True, False]  # blank, once more in JSON, then plain
    retry, plain = llm.calls[2]
    assert not plain and PLAIN_REMINDER in retry[-1]["content"]
    assert [r["text"] for r in conn.execute("SELECT text FROM messages WHERE role = 'fish'")] == ["你自己猜嘛"]
    assert MemoryStore(conn).alive() == [] and len(brain.fallbacks) == 1
    brain.llm = FakeLLM(lambda messages, json_mode: chat_json())
    brain.respond("哈哈", now=T0 + timedelta(minutes=1))
    window = [m["content"] for m in brain.llm.calls[-1][0][1:]]
    assert not any("3600" in w or "user" in w for w in window)


def test_an_empty_retry_says_she_drifted_off(tmp_path):
    brain, _, _ = make_brain(tmp_path, lambda messages, json_mode: "")
    assert brain.respond("在吗", now=T0) == FALLBACK_SAY


def test_what_she_says_first_is_cleaned_too(tmp_path):
    llm = FakeLLM([json.dumps({"say": "在干嘛\n\nmood：无聊"}, ensure_ascii=False)])
    out = Reacher(llm, PERSONA).decide(T0, Mood(0.5, 0.5, 0.5), Triggers([Urge(HIM, "bored", "你有点无聊")]), [])
    assert out is not None and out.text == "在干嘛"


# --- promises -------------------------------------------------------------------------------

def test_his_own_line_says_who_promised():
    assert his_line("等我拿到证那天，你给我弹首钢琴曲庆祝，就这么说定了，不许赖") == "her"
    assert his_line("我答应你，等我买到单车第一趟就骑去湖边，给你拍一段鸟叫") == "him"
    assert his_line("咱俩说好了，明年一起去看樱花") == "both"
    assert his_line("说好了你要拦着我别乱花钱") == "her"
    for line in ("你答应过我的事还记得吗", "之前你答应过我啥来着", "我答应室友周末帮他搬书架",
                 "我妈让我保证早点睡", "我保证不了", "我等公交等了好久", "说好的滑板呢？"):
        assert his_line(line) is None, line


def test_a_note_quoting_him_reads_his_persons_as_his():
    assert promise("他说：你答应我，以后少熬夜", "fact") == "her"
    assert promise("他说我答应你，明天带奶油蛋糕来", "fact") == "him"
    assert promise("说好了等他陶艺课结课那天我给他写张贺卡", "fact") == "her"
    assert promise("等他买到单车，第一趟就给我拍一段鸟叫", "event") == "him"


def test_a_promise_filed_as_an_insight_is_kept_as_a_pinned_open_fact(tmp_path):
    store = MemoryStore(connect(tmp_path / "fish.db"))
    kite = store.note("insight", "他答应我，单车买到后第一趟就骑去湖边，给我拍一段鸟叫。", importance=6,
                      now=T0, heard="chat")
    assert (kite.kind, kite.about, kite.pinned, kite.pact, kite.pact_state) == ("fact", "一辈子", True, "him", "open")
    rule = store.note("insight", "他说话算话，说明他靠谱", importance=6, now=T0, heard="chat")
    assert rule.kind == "insight" and rule.pact is None


def test_a_promise_in_his_line_is_kept_when_no_note_was_taken_for_one(tmp_path):
    """The reply that held the note did not parse, or held no note at all: his words are kept."""
    brain, conn, _ = make_brain(tmp_path, lambda messages, json_mode: chat_json(say="好！"))
    brain.respond("我答应你，等我买到单车第一趟就骑去湖边，给你拍一段鸟叫", now=T0)
    (pact,) = MemoryStore(conn).pacts()
    assert pact.pact == "him" and pact.pinned and "拍一段鸟叫" in pact.text


def test_a_note_of_his_promise_filed_as_an_everyday_plan_becomes_the_pact(tmp_path):
    note = {"text": "他打算单车买到后骑去湖边，拍鸟叫给我听", "kind": "insight", "about": "日常"}
    brain, conn, _ = make_brain(tmp_path, lambda messages, json_mode: chat_json(say="好！", notes=[note]))
    brain.respond("我答应你，单车买到后就骑去湖边，拍鸟叫给你听", now=T0)
    (pact,) = MemoryStore(conn).pacts()
    assert pact.text == note["text"] and (pact.kind, pact.pact) == ("fact", "him")


def test_a_promise_is_starred_when_what_it_waits_for_happens_whatever_its_tags(tmp_path):
    store = MemoryStore(connect(tmp_path / "fish.db"))
    pact = store.note("fact", "我答应他：等他陶艺课结课那天，我给他写张贺卡", importance=9, about="一辈子",
                      now=T0, heard="chat")
    assert pact.pact_state == "open" and pact.tags == ()
    assert condition(pact.text) == "陶艺课结课"
    assert triggered("陶艺课结课了！！", [pact]) == {pact.id: "陶艺课结课"}
    assert triggered("今天课好多", [pact]) == {}


def test_when_he_asks_what_was_promised_the_kept_ones_are_shown_too(tmp_path):
    brain, conn, llm = make_brain(tmp_path)
    store = MemoryStore(conn)
    card = store.note("fact", "我答应他：等他陶艺课结课那天，我给他写张贺卡", importance=9, about="一辈子",
                      now=T0, heard="chat")
    store.settle(card.id, "kept", now=T0 + timedelta(days=3))
    assert asks_pact("之前你答应过我啥") and asks_pact("你以前许过我个啥来着") and asks_pact("我欠你个东西，是啥")
    assert not asks_pact("也许明天下雨") and not asks_pact("我答应你")
    brain.respond("之前你答应过我啥来着", now=T0 + timedelta(days=5))
    block = section(llm.calls[-1][0][0]["content"], "你们之间的约定")
    assert "写张贺卡（兑现了）" in block
    brain.respond("今天吃了碗面", now=T0 + timedelta(days=5, minutes=1))
    assert "## 你们之间的约定" not in llm.calls[-1][0][0]["content"]  # nothing open: no section
    assert "（兑现了）" in render_pacts(store.pacts(settled=True))


def test_no_promise_example_in_a_prompt_names_a_concrete_thing():
    """She once answered "what did I promise you" with the example thing of the prompt, nothing in
    her memory behind it. Examples of promises are placeholders."""
    for prompt in sorted(PROMPTS_DIR.glob("*.md")):
        text = prompt.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "一辈子 =" in line and "比如" in line:
                assert "某" in line.split("比如", 1)[1].split("，", 1)[0], prompt.name


# --- days -------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, now, written", [
    ("他下个月七号考陶艺证", T0, "他2月7号考陶艺证"),
    ("他下下周四去 Springfield", T0, "他2月11日周四去 Springfield"),
    ("他昨晚吃了火锅", T0, "他1月24日晚上吃了火锅"),
    ("他的生日是下个月十九号（2027-02-19）", T0, "他的生日是2月19号"),
    ("他今天(2027-01-25)去放风筝了", T0, "他2027-01-25去放风筝了"),
    ("他外婆上周好多了", T0, "他外婆1月18日那周好多了"),
    ("他每个月底交房租", T0, "他每个月底交房租"),
    ("他坐2号线上班", T0, "他坐2号线上班"),
    ("他住8号楼", T0, "他住8号楼"),
    ("他明白了", T0, "他明白了"),
    ("他后天回老家，以后天天打卡", T0, "他1月27日回老家，以后天天打卡"),
])
def test_time_words_are_written_as_the_days_they_name(text, now, written):
    assert absolute(text, now) == written


def test_the_day_of_the_month_next_month_is_a_day():
    assert day_of("他下个月七号考陶艺证", T0) == date(2027, 2, 7)
    assert day_of("他的生日是下个月十九号", T0) is None  # every year's, not one day


def test_a_note_from_the_chat_keeps_the_day_not_the_word(tmp_path):
    store = MemoryStore(connect(tmp_path / "fish.db"))
    exam = store.note("event", "他下个月七号考陶艺证", importance=5, about="日常", now=T0, heard="chat")
    assert (exam.text, exam.happened_on) == ("他2月7号考陶艺证", "2027-02-07")
    two = store.note("event", "他明天去湖边，今天先买风筝", importance=5, about="日常", now=T0, heard="chat")
    assert two.happened_on == "2027-01-25"  # two days named: no one day, as before
    night = store.note("insight", "他今天心情不错", importance=5, now=T0)  # written at night: hours later
    assert night.text == "他今天心情不错"


@pytest.mark.parametrize("cue, today, days", [
    ("上个月中旬公司组织出去玩", date(2027, 3, 10), (date(2027, 2, 11), date(2027, 2, 20))),
    ("上上个月底我去哪了", date(2027, 3, 10), (date(2027, 1, 21), date(2027, 1, 31))),
    ("这个月初我干嘛了", date(2027, 3, 5), (date(2027, 3, 1), date(2027, 3, 5))),
    ("国庆那几天我干嘛了", date(2027, 10, 20), (date(2027, 10, 1), date(2027, 10, 7))),
    ("国庆那几天我干嘛了", date(2027, 3, 1), (date(2026, 10, 1), date(2026, 10, 7))),
    ("十一月中旬", date(2027, 12, 1), (date(2027, 11, 11), date(2027, 11, 20))),
    ("五一去哪玩了来着", date(2027, 6, 1), (date(2027, 5, 1), date(2027, 5, 5))),
])
def test_a_part_of_a_month_and_a_fixed_holiday_name_days(cue, today, days):
    assert window(cue, datetime.combine(today, datetime.min.time())) == days


def test_four_weeks_ago_is_not_three():
    assert spoken(date(2027, 10, 8), date(2027, 11, 4)) == "10月8日，四周前"


# --- notes say what he said -------------------------------------------------------------------

def test_a_note_of_her_own_guess_is_not_his():
    his = "我新家有啥毛病来着"
    hers = "是暖气不热、卫生间还漏水吧"
    assert echoes_her("他新家暖气不热，卫生间漏水", his, hers)
    assert not echoes_her("他新家暖气不热，卫生间漏水", "我新家暖气不热，卫生间还漏水，烦死", "那也太惨了")
    assert echoes_her("他房租1500", "我房租多少来着", "1500吧？")
    assert not echoes_her("他房租1500", "我房租1500", "1500还行")
    assert not echoes_her("他2月7号考陶艺证", "我下个月七号考陶艺证", "2月7号对吧，加油")


def test_the_close_does_not_write_her_guess_down_as_his(tmp_path):
    close = json.dumps({"summary": "他问新家有啥毛病", "gist": "聊新家", "notes": [
        {"text": "他新家暖气不热，卫生间漏水", "kind": "fact", "about": "本人"},
        {"text": "他新家在 Springfield 东边", "kind": "fact", "about": "本人"}]}, ensure_ascii=False)
    brain, conn, _ = make_brain(tmp_path, lambda m, j: chat_json(say="是暖气不热、卫生间还漏水吧"), close=close)
    brain.respond("我新家在 Springfield 东边，有啥毛病来着", now=T0)
    brain.respond("在吗", now=T0 + timedelta(hours=5))  # closes the first chat
    assert [m.text for m in MemoryStore(conn).alive()] == ["他新家在 Springfield 东边"]


def test_a_chat_note_of_her_guess_is_not_written_and_his_own_words_are(tmp_path):
    guess = {"text": "他新家暖气不热，卫生间还漏水", "kind": "fact", "about": "本人"}
    brain, conn, _ = make_brain(tmp_path, lambda m, j: chat_json(say="暖气不热、卫生间还漏水？", notes=[guess]))
    brain.respond("我新家有啥毛病来着", now=T0)
    assert MemoryStore(conn).alive() == []
    brain.respond("对，新家暖气不热，卫生间还漏水", now=T0 + timedelta(minutes=1))
    assert [m.text for m in MemoryStore(conn).alive()] == [guess["text"]]


def test_a_note_about_her_not_recalling_is_not_written(tmp_path):
    store = MemoryStore(connect(tmp_path / "fish.db"))
    assert store.note("fact", "他欠我一样东西，具体是什么我记不清了", importance=5, now=T0, heard="chat") is None


def test_when_he_asks_her_to_remember_and_nothing_came_back_she_is_told_at_his_line(tmp_path):
    brain, conn, llm = make_brain(tmp_path)
    MemoryStore(conn).note("fact", "他在 Springfield 学钢琴", importance=8, about="本人", tags=["钢琴"], now=T0)
    assert asks_recall("我新家有啥毛病来着") and not asks_recall("我跟你说过我不吃辣")
    brain.respond("我新家有啥毛病来着", now=T0)
    assert "什么也没想起来" in llm.calls[-1][0][-1]["content"]
    brain.respond("我学的那个乐器叫啥来着，钢琴？", now=T0 + timedelta(minutes=1))
    assert "什么也没想起来" not in llm.calls[-1][0][-1]["content"]  # his line touches her card
    brain.respond("你猜我今天吃啥", now=T0 + timedelta(minutes=2))
    assert "什么也没想起来" not in llm.calls[-1][0][-1]["content"]


def test_the_night_merge_sees_which_of_two_notes_is_newer(tmp_path):
    store = MemoryStore(connect(tmp_path / "fish.db"))
    old = store.add("fact", "他在看一套带书架的房子，还在纠结", importance=6, now=T0)
    new = store.add("fact", "他搬了新家，带书架，暖气不热", importance=6, now=T0 + timedelta(days=20))
    llm = FakeLLM(lambda messages, json_mode: json.dumps({"merges": []}))
    Consolidator(llm, PERSONA).merge_pairs([(old, new)])
    sent = llm.calls[0][0][-1]["content"]
    assert "（2027-01-25 记的）他在看一套" in sent and "（2027-02-14 记的）他搬了新家" in sent
    assert "按后记的那条写现在的情况" in sent


# --- the held-out scripts stay out of the prompts ---------------------------------------------

def test_no_prompt_holds_an_answer_of_a_held_out_script():
    """FISH_HELDOUT_SCRIPTS: paths (os.pathsep between) of checkup scripts kept out of the repo. Their
    answers must not be in any prompt either (tests/test_v3_writing.py does it for evals/)."""
    paths = [p for p in os.environ.get("FISH_HELDOUT_SCRIPTS", "").split(os.pathsep) if p]
    if not paths:
        pytest.skip("no held-out script given")
    ordinary = {"生日", "过敏", "面试"}  # a kind of thing, not one answer
    keys = set()
    for path in paths:
        script = json.loads(Path(path).read_text(encoding="utf-8"))
        keys |= set(script.get("forbidden", []))
        for fact in script["facts"]:
            keys |= set(fact.get("keys", [])) | {k for p in fact["probes"] for k in p.get("keys", [])}
    for prompt in sorted(PROMPTS_DIR.glob("*.md")):
        text = prompt.read_text(encoding="utf-8")
        assert [k for k in sorted(keys - ordinary) if k in text] == [], prompt.name

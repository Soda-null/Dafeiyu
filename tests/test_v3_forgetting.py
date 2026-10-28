"""Memory v3 step 7, the forgetting numbers (docs/memory_v3_zh.md §5, waiting for the user's
approval): only a real recall strengthens, ceilings for passing things, unconfirmed rules and the
old "没问成" events, a floor for facts about him himself, nothing below CUED_RECALL_R recalled,
and her own threads folded at a looser bar with at most thirty alive."""

from datetime import datetime, timedelta

from fish.memory import BigramEmbedder, MemoryStore, overlap, recall
from fish.memory import longterm as lt
from fish.memory import retrieval as rt
from fish.memory import stability as st
from fish.memory.when import TimeCued
from fish.storage import connect

T0 = datetime(2027, 1, 6, 20, 0)


def store_at(tmp_path) -> MemoryStore:
    return MemoryStore(connect(tmp_path / "fish.db"))


# --- only a real recall makes a memory stronger ------------------------------------------------

def test_a_glance_is_shown_but_changes_nothing_and_a_real_recall_strengthens(tmp_path):
    store = store_at(tmp_path)
    dinner = store.add("event", "他和室友去吃了麻辣烫", importance=4, now=T0 - timedelta(days=3))
    games = store.add("event", "他周末在宿舍打了一下午游戏", importance=4, tags=["游戏"],
                      now=T0 - timedelta(days=3))
    cue = "我今晚和室友打游戏"
    assert 0 < BigramEmbedder().relevance(cue, dinner) < rt.TOUCH_RELEVANCE  # 室友, nothing more

    got = {r.memory.id: r for r in recall(store, cue, T0)}
    assert set(got) == {dinner.id, games.id}  # both are in front of her
    assert store.get(dinner.id) == dinner  # a glance: no stronger, not fresher, not counted
    after = store.get(games.id)
    assert after.recall_count == 1 and after.stability > games.stability


def test_a_memory_from_the_day_he_names_counts_as_recalled(tmp_path):
    store = store_at(tmp_path)
    dinner = store.add("event", "他2027-01-05晚上和室友吃了麻辣烫", importance=3,
                       now=datetime(2027, 1, 5, 22, 0))
    cue = "昨晚我吃的啥你记得不"
    assert BigramEmbedder().relevance(cue, dinner) < rt.TOUCH_RELEVANCE
    got = recall(store, cue, T0, embedder=TimeCued(BigramEmbedder(), T0))
    assert [r.memory.id for r in got] == [dinner.id]
    assert store.get(dinner.id).recall_count == 1  # the day he named is a real reason


def test_a_month_he_names_brings_things_back_but_only_as_a_glance(tmp_path):
    store = store_at(tmp_path)
    game = store.add("event", "他和室友去看了一场篮球赛", importance=4, stability=19.4,
                     now=datetime(2026, 12, 15, 21, 0))
    cue = "上个月我过得好累"
    timed = TimeCued(BigramEmbedder(), T0)
    assert BigramEmbedder().relevance(cue, game) == 0 and timed.on_named_day(cue, game)
    got = recall(store, cue, T0, embedder=timed)
    assert [r.memory.id for r in got] == [game.id]  # in front of her: it was last month
    assert store.get(game.id) == game  # but a whole month in common is not a reason


# --- ceilings ------------------------------------------------------------------------------

def test_a_passing_thing_never_gets_past_two_weeks_however_often_it_comes_back(tmp_path):
    store = store_at(tmp_path)
    bbq = store.note("event", "他晚上和同学去吃烧烤", importance=3, about="路过", arousal=1.0,
                     tags=["烧烤"], now=T0)
    assert bbq.stability == st.PASSING_MAX_DAYS  # 4 x (1 + 3) = 16 days without the ceiling
    now = T0
    for _ in range(40):  # the 小周 replay: 麻辣烫 recalled 47 times went from 5 to 128 days
        now += timedelta(days=5)
        recall(store, "又想吃烧烤了", now)
    assert store.get(bbq.id).recall_count == 40
    assert store.get(bbq.id).stability == st.PASSING_MAX_DAYS

    other = store.note("event", "他晚上和室友去吃烧烤，喝了点啤酒", importance=3, about="路过",
                       tags=["啤酒"], now=now)
    merged = store.merge([bbq.id, other.id], "他晚上去吃烧烤", now=now)
    assert merged.about == "路过" and merged.stability == st.PASSING_MAX_DAYS
    fixed = store.correct(merged.id, "他晚上去吃的是火锅", now=now)
    assert fixed.stability == st.PASSING_MAX_DAYS  # importance 4 alone would give 19 days


def test_an_unconfirmed_rule_stops_at_three_weeks_until_its_third_day(tmp_path):
    store = store_at(tmp_path)
    rule = store.note("insight", "他一紧张就爱讲冷笑话", importance=5, tags=["冷笑话"], now=T0)
    assert rule.unconfirmed and rule.stability == st.UNCONFIRMED_DAYS
    for i in range(1, 20):
        store.touch(rule.id, T0 + timedelta(days=10 * i, hours=1))
    assert store.get(rule.id).stability == st.UNCONFIRMED_MAX_DAYS
    store.happened_again(rule.id, T0 + timedelta(days=200))
    confirmed = store.happened_again(rule.id, T0 + timedelta(days=201))
    assert confirmed.about == "本人" and confirmed.stability == st.stability_from("本人", 0.0)


def test_an_old_unasked_event_fades_within_weeks_and_rows_from_before_are_not_cut(tmp_path):
    store = store_at(tmp_path)
    unasked = store.add("event", "他一直没问成他那份作业最后交上了没有", importance=5, stability=9.3,
                        now=T0)  # a merge made her the subject "他" (v23 #123); still hers
    old_bbq = store.add("event", "他晚上和同学去吃烧烤。", importance=6, stability=112.1, now=T0)
    store.conn.execute("UPDATE memories SET about = '路过' WHERE id = ?", (old_bbq.id,))
    for i in range(1, 10):
        for m in (unasked, old_bbq):
            store.touch(m.id, T0 + timedelta(days=30 * i))
    assert store.get(unasked.id).stability == st.UNASKED_MAX_DAYS
    assert store.get(old_bbq.id).stability == 112.1  # above its ceiling already: no higher, no lower
    his = store.note("event", "他一直没问成导师能不能延期答辩，挺焦虑的", importance=5, about="日常",
                     now=T0)
    assert his.ceiling == st.INFINITE  # his own worry, not one of her old let-go follow-ups
    for i in range(1, 6):
        store.touch(his.id, T0 + timedelta(days=30 * i))
    assert store.get(his.id).stability > st.UNASKED_MAX_DAYS
    life = store.note("fact", "他生日是3月14日", importance=10, about="一辈子", now=T0)
    assert store.touch(life.id, T0 + timedelta(days=9)).stability == st.INFINITE


# --- a floor for him himself, and what is gone stays out of recall ---------------------------

def test_a_fact_about_him_himself_grows_unsure_but_is_never_lost(tmp_path):
    store = store_at(tmp_path)
    home = store.note("fact", "他老家在Springfield", importance=8, about="本人", tags=["老家"], now=T0)
    job = store.note("fact", "他在学校书店打工", importance=5, about="日常", tags=["打工"], now=T0)
    rule = store.note("insight", "他不爱说自己家里的事", importance=5, now=T0)
    store.happened_again(rule.id, T0 + timedelta(days=1))
    rule = store.happened_again(rule.id, T0 + timedelta(days=2))
    assert rule.about == "本人"

    later = T0 + timedelta(days=3 * 365)  # three years without a word about it
    home, job, rule = store.get(home.id), store.get(job.id), store.get(rule.id)
    assert home.retrievability(later) == st.HIMSELF_R_FLOOR and home.fuzzy(later)
    assert job.retrievability(later) < st.CUED_RECALL_R
    assert rule.retrievability(later) < st.CUED_RECALL_R  # the floor is for facts, not for her rules

    got = recall(store, "我老家是哪来着", later)
    assert [r.memory.id for r in got] == [home.id] and got[0].fuzzy  # "好像是 Springfield？"
    assert recall(store, "我以前打工的事你还记得吗", later) == []  # a tag hit cannot wake it
    assert job.id in {m.id for m in store.alive()}  # out of recall, not deleted


# --- her own life ---------------------------------------------------------------------------

def test_her_own_thread_told_in_new_words_is_one_memory(tmp_path):
    store = store_at(tmp_path)
    first = store.note("self", "我每晚数米粒，数到三十七就乱，明天重新数，目标一百", importance=4, now=T0)
    again = "我每晚数米粒，老是卡在三十七"
    assert lt.SELF_REPEAT_SIMILARITY <= overlap(again, first.text) < lt.REPEAT_SIMILARITY
    same = store.note("self", again, importance=4, now=T0 + timedelta(days=1))
    assert same.id == first.id and same.times == 2
    tank = store.note("self", "鱼缸一直挤得鱼翻身都难，想换大的还没换", importance=4, now=T0 + timedelta(days=2))
    assert tank.id != first.id
    # his things keep the usual bar: two evenings of his are two memories
    a = store.note("event", "他每晚背单词，背到三十七个就乱，明天重新背，目标一百", importance=4, now=T0)
    b = store.note("event", "他每晚背单词，老是卡在三十七个", importance=4, now=T0 + timedelta(days=1))
    assert a.id != b.id


def test_no_more_than_thirty_of_her_own_threads_stay_alive(tmp_path):
    store = store_at(tmp_path)
    threads = ["我" + "".join(chr(0x4E00 + 4 * i + k) for k in range(4)) for i in range(31)]  # no char shared
    notes = [store.note("self", t, importance=4 if i else 3, now=T0 + timedelta(minutes=i))
             for i, t in enumerate(threads)]
    assert len({n.id for n in notes}) == 31  # all different threads
    alive = store.alive("self")
    assert len(alive) == lt.KIND_CAPS["self"] == 30
    gone = store.get(notes[0].id)  # the weakest
    assert gone.superseded_by == notes[-1].id and gone.why == "cap"
    assert store.former(notes[-1].id) is None  # pushed out is not "what she used to think"

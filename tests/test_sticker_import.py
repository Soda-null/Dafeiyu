"""Giving her many stickers at once: a folder goes into the inbox, she names each picture now,
the same picture is kept once, and a big album still shows her the ones she has not tried."""

import json
import random
from datetime import datetime

from fish.__main__ import give_stickers
from fish.brain import FakeLLM
from fish.routines.stickers import MAX_BYTES, adopt_inbox, import_folder, inbox_of
from tests.test_pictures import make_brain, png

T = datetime(2026, 10, 28, 12, 0)


def naming():
    count = {"n": 0}

    def respond(messages, json_mode):
        count["n"] += 1
        return json.dumps({"caption": f"第{count['n']}张的叫法", "tags": ["好玩"]}, ensure_ascii=False)
    return FakeLLM(respond)


def test_a_folder_is_copied_flat_into_the_inbox(tmp_path):
    src = tmp_path / "表情包"
    (src / "猫").mkdir(parents=True)
    (src / "a.png").write_bytes(png((1, 1, 1)))
    (src / "猫" / "a.PNG").write_bytes(png((2, 2, 2)))
    (src / "说明.txt").write_text("不是图")
    inbox = tmp_path / "inbox"
    assert import_folder(src, inbox) == 2
    # two pictures, neither lost: on the Mac a.PNG lands on a.png and is renamed; on the box
    # (Linux tells the cases apart) both names are free
    probe = tmp_path / "probe.png"
    probe.write_bytes(b"")
    case_blind = (tmp_path / "PROBE.PNG").exists()
    assert sorted(p.name for p in inbox.iterdir()) == (["a-1.PNG", "a.png"] if case_blind else ["a.PNG", "a.png"])
    assert (src / "a.png").exists()  # copied, not moved


def test_she_names_them_all_now_and_keeps_a_repeat_once(tmp_path):
    llm = naming()
    conn, brain = make_brain(tmp_path, llm)
    inbox = inbox_of(brain)
    inbox.mkdir(parents=True)
    for k in range(12):  # more than the ten a night
        (inbox / f"{k:02}.png").write_bytes(png((k, 0, 0)))
    (inbox / "again.png").write_bytes(png((0, 0, 0)))  # the same picture as 00.png
    (inbox / "fake.jpg").write_bytes(b"not a picture")
    (inbox / "huge.png").write_bytes(png() + b"\0" * MAX_BYTES)
    done = adopt_inbox(brain, T)
    assert len(done.added) == 12 and done.repeats == 1
    assert brain.album.count() == 12 and len(llm.calls) == 12
    assert sorted(p.name for p in inbox.iterdir()) == ["fake.jpg", "huge.png"]
    assert any("不是图片" in w for w in done.left) and any("太大了" in w for w in done.left)


def test_old_stickers_without_a_digest_still_count_as_repeats(tmp_path):
    conn, brain = make_brain(tmp_path, naming())
    s = brain.album.add(png((9, 9, 9)), "image/png", "老的", now=T)
    conn.execute("UPDATE stickers SET digest = NULL WHERE id = ?", (s.id,))
    assert brain.album.has(png((9, 9, 9))) and not brain.album.has(png((8, 8, 8)))


def test_a_big_album_shows_favourites_and_a_changing_rest(tmp_path):
    conn, brain = make_brain(tmp_path, naming())
    for k in range(40):
        brain.album.add(png((k, 1, 1)), "image/png", f"图{k}", now=T)
    brain.album.touch(1, T)
    first = brain.album.offer(rng=random.Random(1))
    second = brain.album.offer(rng=random.Random(2))
    assert len(first) == 30 and first[0].id == 1 and second[0].id == 1
    assert {s.id for s in first} != {s.id for s in second}
    assert len({s.id for s in first}) == 30
    small_conn, small = make_brain(tmp_path / "small", naming())
    small.album.add(png(), "image/png", "唯一一张", now=T)
    assert [s.caption for s in small.album.offer()] == ["唯一一张"]


def test_fish_stickers_prints_what_she_called_each(tmp_path, capsys):
    conn, brain = make_brain(tmp_path, naming())
    src = tmp_path / "攒的"
    src.mkdir()
    (src / "x.png").write_bytes(png((5, 5, 5)))
    give_stickers(brain, src)
    out = capsys.readouterr().out
    assert "放进收件箱 1 张" in out and "第1张的叫法" in out and "现在一共 1 张" in out

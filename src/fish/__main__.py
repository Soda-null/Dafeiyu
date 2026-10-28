"""`python3 -m fish [chat | nightly | browse | life [天数] | show | stickers [folder] | cottage [put 东西 [顿数] | sill 东西] | wechat [login]]`.

chat          talk to her in the terminal (default). Runs the nightly routine first if due.
life          her day on one screen: what she is doing, her room, today, this stretch, the last
              few diaries (`life 7` for a week of them). No memories: that is `show`.
nightly       run the nightly routine now (safe to repeat: once per day).
browse        make her browse now (by hand only: she browses in her free time when she likes, decision 24).
show          print what she remembers: profile, memories, follow-ups, episodes, diary, mood.
stickers      give her the pictures in a folder (and whatever is in data/stickers/inbox/): she
              looks at each now, names it and keeps it. The folder's files are copied, not moved.
cottage       show her cottage as it is now (decision 26). `cottage put 鸡蛋 [顿数]` puts food in
              (米 fills the rice jar); `cottage sill 一盆薄荷` puts a present on her windowsill.
wechat login  show a QR code; scan it in WeChat to bind her to your account.
wechat        answer you on WeChat until Ctrl-C.
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from fish.brain import Brain, DeepSeekLLM
from fish.channels import ILinkClient, TerminalChannel, WeChatChannel, WeChatState, login
from fish.channels.wechat import STATE_FILE
from fish.config import REPO_ROOT, Settings, load_settings, owner_words
from fish.cottage import Cottage
from fish.brain.leisure import away, moment_line
from fish.brain.leisure.book import where
from fish.memory import (Diary, EpisodeManager, MemoryStore, Pastimes, PhaseStore, ProspectiveStore,
                         Relationship, TraitStore)
from fish.mood import MoodStore, stage_of
from fish.routines import run_browse, run_nightly
from fish.routines.outside import run_outside
from fish.routines.nightly import EXPORT_PATH
from fish.routines.stickers import STICKER_TYPES, adopt_inbox, import_folder, inbox_of
from fish.storage import connect
from fish.world import WikiSearcher, read_page

WECHAT_STATE = REPO_ROOT / STATE_FILE
EXPORT_FILE = REPO_ROOT / EXPORT_PATH


def show(conn: sqlite3.Connection, now: datetime | None = None) -> None:
    now = now or datetime.now()
    store = MemoryStore(conn)
    print("== 底牌（每轮都带）==")
    for m in store.profile():
        print(f"  [#{m.id}] {m.text}")
    print(owner_words("== 和他相处的方式 =="))
    for m in store.howto_card():
        print(f"  [#{m.id}] {m.text}")
    print("== 长期条目（现行）==")
    for m in store.alive():
        r = m.retrievability(now)
        if m.pinned:
            flag = "钉住"
        elif r < 0.1:
            flag = "想不起"
        elif r < 0.5:
            flag = "模糊"
        else:
            flag = "清楚"
        where = f"  ← {m.source}" if m.source else ""
        print(f"  [#{m.id}] {m.kind:7} 重要{m.importance:2} R={r:.2f} {flag}  {m.line()}{where}")
    print("== 惦记 ==")
    for f in ProspectiveStore(conn).open():
        print(f"  [#{f.id}] {f.due}  {f.text}")
    print("== 最近的聊天 ==")
    for ep in EpisodeManager(conn).recent(3):
        print(f"  {ep.started[:16]}  {ep.gist or ep.summary[:60] or '（无摘要）'}")
    print("== 日记 ==")
    for day, text in Diary(conn).recent(3):
        print(f"  {day}  {text}")
    rel = Relationship(conn)
    stage = stage_of(rel.closeness)
    mood = MoodStore(conn).load()
    print(f"== 当日心情 == {mood.describe(stage)}  (精力 {mood.energy:.0f} 无聊 {mood.boredom:.0f} 饿 {mood.hunger:.0f})")
    phase = PhaseStore(conn).current()
    print(f"== 这阵子 == {phase.line or '（还没写）'}  (基调 {phase.tone:+.2f} {phase.tone_word}，劲头 {phase.drive:.2f} {phase.drive_word}；在意：{'、'.join(phase.focus) or '—'})")
    traits = TraitStore(conn)
    print(f"== 底色 == {'；'.join(traits.describe()) or '还是刚认识时的样子'}")
    for g in traits.growth_notes(2):
        print(f"  {g.month[:7]} 回头看：{g.text}  {g.changes}")
    print(f"== 关系 == {rel.stats(now)}  亲近 {rel.closeness:.0f}（{stage}）")
    pastimes = Pastimes(conn)
    moments = [m for m in pastimes.moments(now - timedelta(days=14)) if m.choice]
    counts = Counter(m.choice for m in moments)
    print(f"== 空闲（两周 {len(moments)} 段）== " + ("，".join(f"{k} {v}" for k, v in counts.most_common()) or "还没有"))
    for m in moments[-6:]:
        print(f"  {m.ts[:10]} {moment_line(m)}" + (f"  ——{m.why}" if m.why else ""))
    for p in pastimes.all()[:5]:
        status = {"on": where(p) if p.kind == "book" else "在追", "dropped": "弃了", "finished": "读完了"}[p.status]
        print(f"  在追的：{p.title}（{status}，上次 {p.touched[:10]}）")


def life(conn: sqlite3.Connection, settings: Settings, days: int = 3, now: datetime | None = None) -> None:
    """Her life, not her memory: what she is doing and what her day was, in one screen."""
    now = now or datetime.now()
    print(f"== 她现在（{now:%m-%d %H:%M}）==")
    events: list[str] = []
    if settings.cottage:
        home = Cottage(settings.db_path.parent / "cottage" / "now.json")
        try:
            room = home.load(now)
        except ValueError as e:
            raise SystemExit(str(e))
        if room.doing:
            print("  " + home.doing_line(room).replace("你", "她", 1))
        for line in home.lines(room).values():
            print(f"  {line}")
        events = home.today(room, now)
    mood = MoodStore.apply_clock(MoodStore(conn).load(), now)
    print(f"  心情：{mood.describe()}")
    phase = PhaseStore(conn).current()
    if phase.line:
        print(f"  这阵子：{phase.line}")
    pastimes = Pastimes(conn)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    events += [moment_line(m) for m in pastimes.moments(midnight, now) if away(m)]
    print("== 今天 ==")
    for line in sorted(events) or ["还没什么事"]:
        print(f"  {line}")
    reading = [p.title for p in pastimes.all() if p.status == "on"][:3]
    if reading:
        print(f"  在读 / 在追：{'、'.join(reading)}")
    print("== 日记 ==")
    for day, text in Diary(conn).recent(days) or [("", "还没写过")]:
        print(f"  {day}  {text}")


def give_stickers(brain: Brain, folder: Path | None) -> None:
    inbox = inbox_of(brain)
    if folder is not None:
        if not folder.is_dir():
            raise SystemExit(f"没有这个文件夹：{folder}")
        print(f"放进收件箱 {import_folder(folder, inbox)} 张")
    waiting = len([p for p in inbox.iterdir() if p.suffix.lower() in STICKER_TYPES]) if inbox.is_dir() else 0
    print(f"她挨张看（{waiting} 张，一张问一次模型）……")
    done = adopt_inbox(brain, datetime.now())
    for s in done.added:
        print(f"  [#{s.id}] {s.caption}  {'、'.join(s.tags)}")
    print(f"收下 {len(done.added)} 张；相册里本来就有的 {done.repeats} 张；现在一共 {brain.album.count()} 张")
    for why in done.left:
        print(f"  没收：{why}")


def cottage(settings: Settings, sub: str | None, rest: list[str]) -> None:
    """Show her room, or put something in it: only he and the rules change it (decision 26)."""
    home = Cottage(settings.db_path.parent / "cottage" / "now.json")
    now = datetime.now()
    try:
        if sub == "put" and rest:
            print(home.give(rest[0], now, int(rest[1]) if len(rest) > 1 else None))
        elif sub == "sill" and rest:
            print(home.put_on_sill(" ".join(rest), now))
        elif sub is not None:
            raise SystemExit("用法：fish cottage [put 东西 [顿数] | sill 东西]")
        room = home.load(now)
    except ValueError as e:
        raise SystemExit(str(e))
    print(f"== 她的小屋（{home.path}）==")
    if room.doing:
        print(f"  {home.doing_line(room)}")
    for line in home.lines(room).values():
        print(f"  {line}")
    for line in home.today(room, now):
        print(f"  今天 {line}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="fish", description="大肥鱼")
    ap.add_argument("command", nargs="?", choices=["chat", "nightly", "browse", "life", "show", "stickers", "cottage",
                                                   "wechat"], default="chat")
    ap.add_argument("subcommand", nargs="?", help="wechat: login; stickers: a folder of pictures; cottage: put / sill; life: how many diaries")
    ap.add_argument("rest", nargs="*", help="cottage put / sill: what")
    args = ap.parse_args(argv)
    if args.subcommand is not None and (args.command, args.subcommand) != ("wechat", "login") \
            and args.command not in ("stickers", "cottage", "life"):
        ap.error(f"unexpected argument: {args.subcommand}")
    if args.rest and args.command != "cottage":
        ap.error(f"unexpected argument: {' '.join(args.rest)}")

    settings = load_settings()
    if args.command == "cottage":
        cottage(settings, args.subcommand, args.rest)
        return
    conn = connect(settings.db_path)
    if args.command == "show":
        show(conn)
        return
    if args.command == "life":
        if args.subcommand is not None and not args.subcommand.isdigit():
            ap.error("life 后面只能跟天数，比如 life 7")
        life(conn, settings, int(args.subcommand or 3))
        return
    if args.command == "wechat" and args.subcommand == "login":
        previous = WeChatState.load(WECHAT_STATE) if WECHAT_STATE.exists() else None
        login(ILinkClient(), WECHAT_STATE, previous=previous)
        return

    brain = Brain(conn, settings, DeepSeekLLM(settings), searcher=WikiSearcher(), reader=read_page)
    if args.command == "stickers":
        give_stickers(brain, Path(args.subcommand).expanduser() if args.subcommand else None)
        return
    report = run_nightly(conn, brain=brain, export_path=EXPORT_FILE)
    if args.command == "nightly":
        print(report)
        return
    if args.command == "browse":
        print(run_outside(conn, brain=brain))  # weather and her neighbourhood first
        print(run_browse(conn, brain=brain, force=True))
        return
    run_outside(conn, brain=brain)
    if args.command == "wechat":
        if not WECHAT_STATE.exists():
            raise SystemExit("还没绑微信。先跑：.venv/bin/python -m fish wechat login")
        state = WeChatState.load(WECHAT_STATE)
        client = ILinkClient(state.bot_token, state.base_url)

        upkeep = {"last": datetime.now()}

        def tick(send):
            # today's weather and holiday table (once a day inside); hourly, so no network cannot mean a retry per poll
            if datetime.now() - upkeep["last"] >= timedelta(hours=1):
                upkeep["last"] = datetime.now()
                run_outside(conn, brain=brain)
            return brain.tick(send)

        channel = WeChatChannel(client, state, WECHAT_STATE, tick=tick)
    else:
        channel = TerminalChannel()
    channel.run(lambda incoming: brain.handle(incoming, channel.name))


if __name__ == "__main__":
    main()

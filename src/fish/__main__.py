"""`python3 -m fish [chat | nightly | browse | show | wechat [login]]`.

chat          talk to her in the terminal (default). Runs the nightly and browse routines first if due.
nightly       run the nightly routine now (safe to repeat: once per day).
browse        let her browse now (once per day; this forces it even before 09:30).
show          print what she remembers: profile, memories, follow-ups, episodes, diary, mood.
wechat login  show a QR code; scan it in WeChat to bind her to your account.
wechat        answer you on WeChat until Ctrl-C.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime

from fish.brain import Brain, DeepSeekLLM
from fish.channels import ILinkClient, TerminalChannel, WeChatChannel, WeChatState, login
from fish.channels.wechat import STATE_FILE
from fish.config import REPO_ROOT, load_settings, owner_words
from fish.memory import (Diary, EpisodeManager, MemoryStore, PhaseStore, ProspectiveStore, Relationship,
                         TraitStore)
from fish.mood import MoodStore, stage_of
from fish.routines import run_browse, run_nightly
from fish.routines.outside import run_outside
from fish.routines.nightly import EXPORT_PATH
from fish.storage import connect
from fish.world import WikiSearcher

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
        print(f"  [#{m.id}] {m.kind:7} 重要{m.importance:2} R={r:.2f} {flag}  {m.text}{where}")
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


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="fish", description="大肥鱼")
    ap.add_argument("command", nargs="?", choices=["chat", "nightly", "browse", "show", "wechat"],
                    default="chat")
    ap.add_argument("subcommand", nargs="?", choices=["login"])
    args = ap.parse_args(argv)

    settings = load_settings()
    conn = connect(settings.db_path)
    if args.command == "show":
        show(conn)
        return
    if args.command == "wechat" and args.subcommand == "login":
        previous = WeChatState.load(WECHAT_STATE) if WECHAT_STATE.exists() else None
        login(ILinkClient(), WECHAT_STATE, previous=previous)
        return

    brain = Brain(conn, settings, DeepSeekLLM(settings), searcher=WikiSearcher())
    report = run_nightly(conn, brain=brain, export_path=EXPORT_FILE)
    if args.command == "nightly":
        print(report)
        return
    if args.command == "browse":
        print(run_outside(conn, brain=brain))  # weather and her neighbourhood first
        print(run_browse(conn, brain=brain, force=True))
        return
    run_outside(conn, brain=brain)
    run_browse(conn, brain=brain)  # catch up on today's browse if the timer was missed
    if args.command == "wechat":
        if not WECHAT_STATE.exists():
            raise SystemExit("还没绑微信。先跑：.venv/bin/python -m fish wechat login")
        state = WeChatState.load(WECHAT_STATE)
        client = ILinkClient(state.bot_token, state.base_url)
        channel = WeChatChannel(client, state, WECHAT_STATE, tick=brain.tick)
    else:
        channel = TerminalChannel()
    channel.run(lambda incoming: brain.handle(incoming, channel.name))


if __name__ == "__main__":
    main()

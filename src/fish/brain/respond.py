"""The wiring for one chat turn (docs/memory_design_zh.md §6, docs/nodes_design_zh.md step 2).
Channels call Brain.handle and nothing else.

A turn: each node answers its question (memory: what his line brings to mind; mood: how she
feels now; the cottage: what the room is like; the world: where she lives, what day it is),
the answers become one Situation, the brain proper (reply.py) turns that into her reply, and
what she said and noted is recorded here. The model calls of the chat path are in reply.py,
plus the fold and the close of a chat below.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path

from typing import Callable

from fish.app import wire
from fish.brain.checker import check_home
from fish.brain.leisure import Leisure, LeisureNode, away, default_activities, moment_line, pastimes_line
from fish.brain.llm import LLM
from fish.brain.parse import Reply, parse_episode_close
from fish.brain.prompt import Situation, build_close_messages, build_fold_messages, render_day
from fish.brain.reach import HOME_LATELY, ReachNode, ReachOut
from fish.bus import Bus
from fish.clock import Clock
from fish.brain.reply import FALLBACK_SAY, PLAIN_REMINDER, Replier, plain_text  # noqa: F401 (tests import them here)
from fish.config import Settings, owner_words
from fish.cottage import Cottage, RoomNode, invented_act
from fish.messages import Incoming, Outgoing, data_url, sniff_mime
from fish.msgs import Chatted, HeSaid, SheSaid
from fish.memory import (ABOUT_HIM_KINDS, FOLD_BATCH, PACT_LINK, Diary, Episode, EpisodeManager, Memory,
                         MemoryStore, Moment, Pastimes, PhaseStore, ProspectiveStore, Recollector, Relationship,
                         StickerAlbum, TraitStore, Window, asks_recall, echoes_her, his_line, keys_of, overlap,
                         promised_in_words)
from fish.mood import Mood, MoodNode, MoodStore, stage_of
from fish.persona import load_persona, load_stages
from fish.world import Searcher, day_line, load_home, load_places, places_line, read_file

PROMISE_CHARS = 120  # how much of his line is kept when it is the only record of a promise
CLOSE_TOKENS = 800  # the close writes a summary, notes, results: cut short, its JSON would not parse
SHARED_CHARS = 2500  # how much of a page or file he shared she reads (decision 23)
URL = re.compile(r"https?://[^\s，。！？、；（）()【】<>\"']+")
PageReader = Callable[[str], tuple[str, str]]  # url -> (title, text); world.read_page


def echoed(kind: str, text: str, his: str, hers: str) -> bool:
    """A note about him whose words are hers in this chat, not his (longterm.echoes_her). Her own
    doings and promises ("我答应他……") are hers to write. Asked only in a chat where he asked her to
    remember (`echo_checked`)."""
    return kind in ABOUT_HIM_KINDS and not text.lstrip().startswith("我") and echoes_her(text, his, hers)


def echo_checked(his_lines: list[str]) -> bool:
    """Her guesses are written down as his only when he asked her to remember something ("我新家有
    啥毛病来着"): there she answers with what she thinks he said, and a wrong guess would become a
    memory. Anywhere else her words in a note are a follow-up he answered ("面试怎么样了？" "过了！")
    or his news said back to him. (A made-up turn of his already drops the reply's notes: parse.py.)"""
    return any(asks_recall(line) for line in his_lines)


class Brain:
    def __init__(self, conn: sqlite3.Connection, settings: Settings, llm: LLM, *,
                 persona_text: str | None = None, window_size: int | None = None,
                 fold_batch: int | None = None, searcher: Searcher | None = None,
                 stages: dict[str, str] | None = None, stickers_dir: Path | None = None,
                 reader: PageReader | None = None) -> None:
        self.conn = conn
        self.settings = settings
        self.replier = Replier(llm, searcher)  # the brain proper: Situation in, reply out
        self.reader = reader  # None: she does not open links he sends
        # Her pictures and her home live next to her database (data/ for real, a temp dir in tests).
        self.album = StickerAlbum(conn, stickers_dir or settings.db_path.parent / "stickers")
        self.persona = persona_text if persona_text is not None else load_persona()
        self.stages = stages if stages is not None else (load_stages() if persona_text is None else {})
        self.window = Window(conn, window_size or settings.window_size, fold_batch or FOLD_BATCH)
        self.episodes = EpisodeManager(conn)
        self.store = MemoryStore(conn)
        self.prospective = ProspectiveStore(conn)
        self.diary = Diary(conn)
        self.moods = MoodStore(conn)
        self.relationship = Relationship(conn)
        self.phases = PhaseStore(conn)
        self.traits = TraitStore(conn)
        self.pastimes = Pastimes(conn)
        self.leisure: Leisure | None = None  # built on the first free moment; tests set their own
        # her lakeside cottage (decision 26), next to her database like her pictures; None when off
        self.cottage = Cottage(settings.db_path.parent / "cottage" / "now.json") if settings.cottage else None
        self.home_fixes: list[dict] = []  # her lines the checker mended (decision 38); the checkup reads them
        self.recollector = Recollector(conn, store=self.store, prospective=self.prospective,
                                       episodes=self.episodes, window=self.window, diary=self.diary,
                                       phases=self.phases, relationship=self.relationship)
        # the nodes that live on time (docs/nodes_design_zh.md step 3), wired in app.py
        self.bus = Bus()
        self.clock = Clock(self.bus)
        self._say: Callable[[str], bool] = lambda text: False  # the channel's send, set each tick
        self._channel = "wechat"
        self._first_lines = 0  # lines she said first, so tick can tell its channel
        self.reach = ReachNode(self.bus, conn, enabled=settings.reach_out, max_per_day=settings.reach_max_per_day,
                               llm=lambda: self.llm, persona=self.persona, window=self.window,
                               kitchen=self.cottage is not None, home_lately=self.home_lately,
                               say=lambda text: self._say(text), channel=lambda: self._channel,
                               room=lambda now, mood: self.cottage_text(now, mood.hunger),
                               record=lambda now: self.room.record(now) if self.room is not None else "",
                               fixed=self.home_fixes.append)
        self.leisure_node = LeisureNode(self.free_time)
        self.room = RoomNode(self.bus, self.cottage) if self.cottage is not None else None
        self.mood_node = MoodNode(self.moods, kitchen=self.cottage is not None)
        wire(self.bus, room=self.room, mood=self.mood_node, reach=self.reach, leisure=self.leisure_node,
             chat=self.keep_her_line)

    # the model and the searcher belong to the brain proper; tests swap the model after building
    @property
    def llm(self) -> LLM:
        return self.replier.llm

    @llm.setter
    def llm(self, llm: LLM) -> None:
        self.replier.llm = llm

    @property
    def searcher(self) -> Searcher | None:
        return self.replier.searcher

    @searcher.setter
    def searcher(self, searcher: Searcher | None) -> None:
        self.replier.searcher = searcher

    @property
    def fallbacks(self) -> list[dict]:
        return self.replier.fallbacks

    @property
    def empty_firsts(self) -> int:
        return self.replier.empty_firsts

    def ask(self, messages: list[dict]) -> Reply:
        return self.replier.ask(messages)

    def stage(self) -> str:
        return stage_of(self.relationship.closeness)

    def place_fields(self) -> dict[str, str]:
        """Where she lives, today's weather, what is nearby (decision 15); empty until known."""
        folder = self.album.folder.parent / "home"
        home = load_home(folder)
        return {"home_line": home.line() if home else "",
                "weather_line": self.relationship.get("weather_line", "") or "",
                "places": places_line(load_places(folder))}

    def move_time(self, now: datetime) -> None:
        """Bring her cottage up to now (decision 26) before a chat turn; the room node says
        on the bus what that did to her (step 4)."""
        if self.room is not None:
            self.room.step(now)

    def home_lately(self, now: datetime) -> list[str]:
        """What happened in her cottage in the last few hours: a reason to text him (decision
        26). Only recent, so one event does not knock on the gate all day; never a meal eaten on
        time, or she texts "饭做好了" twice a day (the 10-28 trial)."""
        return self.room.lately(now, HOME_LATELY) if self.room is not None else []

    def cottage_text(self, now: datetime, hunger: float, energy: float | None = None) -> str:
        return self.room.view(now, hunger, energy) if self.room is not None else ""

    def day_fields(self, now: datetime) -> dict[str, str]:
        """What day it is, what she is following, what she did with her free time today (decision 24)."""
        today = datetime.combine(now.date(), datetime.min.time())
        done = [moment_line(m) for m in self.pastimes.moments(today, now) if away(m)][-3:]
        return {"day_line": day_line(now.date(), self.album.folder.parent / "home"),
                "pastimes_line": pastimes_line(self.pastimes, now),
                "today_line": "你今天空闲时：" + "；".join(done) + "。" if done else ""}

    def growth_lines(self) -> list[str]:
        lines = self.traits.describe()
        notes = self.traits.growth_notes(1)
        if notes:
            lines.append(f"你上次回头看自己（{notes[0].month[:7]}）：{notes[0].text}")
        return lines

    # --- the turn ------------------------------------------------------------

    def respond(self, user_text: str, channel: str = "terminal",
                now: datetime | None = None, image: bytes | None = None) -> str:
        return self.handle(Incoming(user_text, image), channel, now).text

    def handle(self, incoming: Incoming, channel: str = "terminal",
               now: datetime | None = None) -> Outgoing:
        now = now or datetime.now()
        self.bus.publish(HeSaid(incoming.text, now, channel, image=incoming.image,
                                file_name=incoming.file.name if incoming.file else "",
                                file_data=incoming.file.data if incoming.file else None))
        stale = self.episodes.stale(now)
        if stale is not None:
            self.close_episode(stale, now)
        ep = self.episodes.open_episode() or self.episodes.start(channel, now)

        self.move_time(now)
        base = self.moods.load()
        mood = MoodStore.apply_clock(base, now, kitchen=self.cottage is not None)  # what she feels now; the baseline is what we save
        stage = self.stage()
        self.relationship.note_active_day(now)

        sit, shared_note = self.situation(incoming, ep, mood, stage, now)
        reply, seen_source = self.replier.reply(sit)
        if reply.do and self.room is not None:  # she said she is off to do it: the room does it now
            self.room.act(reply.do, now, reply.do_arg)
        if self.room is not None:  # what she says of her home, held against the room (decision 38)
            reply.say, why = check_home(self.llm, self.room.record(now), incoming.text, reply.say)
            if why:
                self.home_fixes.append({"at": now.isoformat(timespec="minutes"), "why": why, "said": reply.say})
        return self.remember_turn(incoming, reply, seen_source, shared_note, ep.id, now, channel)

    def situation(self, incoming: Incoming, ep: Episode, mood: Mood, stage: str,
                  now: datetime) -> tuple[Situation, str]:
        """Each node's answer for this turn, put together; and the note kept in the chat for
        what he shared."""
        r = self.recollector.recollect(incoming.text, ep, now, pages=self.settings.pages, him=owner_words("他"))
        shared, shared_note = self.open_shared(incoming)
        image = incoming.image
        sit = Situation(
            persona=self.persona, now=now, mood=mood,
            relationship=self.relationship.stats(now),
            profile=r.profile, mentioned={m.id for m in r.touched}, formers=r.formers,
            diary=r.diary,
            recalled=r.recalled, followups=r.followups,
            earlier=render_day(r.day), window=list(r.day.current), user_text=incoming.text,
            limit=self.settings.prompt_chars,
            seen=r.seen,
            stage=stage, stage_rules=self.stages.get(stage, ""), howto=r.howto,
            phase=r.phase, growth=self.growth_lines(), **self.place_fields(),
            **self.day_fields(now), cottage=self.cottage_text(now, mood.hunger, mood.energy),
            stickers=self.album.offer(), user_image=data_url(image) if image else None,
            shared=shared, today_section=r.today, pacts=r.pacts, stars=r.stars,
            pages=r.pages, nothing_found=r.nothing_found,
        )
        return sit, shared_note

    def remember_turn(self, incoming: Incoming, reply: Reply, seen_source: str | None, shared_note: str,
                      episode_id: int, now: datetime, channel: str) -> Outgoing:
        """What this turn leaves behind: both lines in the chat, her notes, a sticker kept or
        sent, how the turn moved her mood and closeness; the chat folded when it runs long."""
        user_text, image = incoming.text, incoming.image
        stored_text = user_text
        if image is not None:
            stored_text = f"[图片：{reply.image_note}]" if reply.image_note else "[图片]"
            if user_text and user_text != "[图片]":
                stored_text += " " + user_text
        if shared_note:
            stored_text += shared_note
        outgoing = Outgoing(reply.say)
        if reply.sticker is not None:
            try:
                s = self.album.get(reply.sticker)
                if s.path.exists():
                    self.album.touch(reply.sticker, now)
                    outgoing = Outgoing(reply.say, s.path, s.caption)
            except KeyError:
                pass
        self.window.append("user", stored_text, channel, episode_id, now)
        if reply.say.strip():  # silence is a real answer sometimes; it leaves no bubble
            self.window.append("fish", reply.say, channel, episode_id, now)
        elif outgoing.sticker is not None:  # a sticker alone is an answer too: the chat keeps that she sent it
            self.window.append("fish", f"[表情包：{outgoing.sticker_caption}]", channel, episode_id, now)
        self.episodes.touch(episode_id, now)
        self.record(reply, episode_id, now, seen_source=seen_source, said=user_text)
        if image is not None and reply.keep_sticker:
            self.album.add(image, sniff_mime(image) or "image/jpeg", reply.keep_sticker, now=now)

        if reply.say.strip() or outgoing.sticker is not None:
            self.bus.publish(SheSaid(reply.say, now, channel,
                                     sticker=str(outgoing.sticker) if outgoing.sticker else ""))
        # how the turn moved her is the mood node's to work out (nodes step 5)
        self.bus.publish(Chatted(now, user_text, reply.say, mood=reply.mood, topic=reply.topic,
                                 last_topic=self.relationship.get("last_topic")))
        self.relationship.bump_closeness(reply.mood, now)
        if reply.topic:
            self.relationship.set("last_topic", reply.topic, now)

        self.fold_if_needed(episode_id)
        return outgoing

    def open_shared(self, incoming: Incoming) -> tuple[str, str]:
        """What he shared, for her to look at once (decision 23): a file he sent, else the
        first link in his message. Returns (the prompt block, a short note kept in the chat)."""
        if incoming.file is not None:
            name = incoming.file.name
            text = read_file(name, incoming.file.data, SHARED_CHARS)
            if text is None:
                return (owner_words(f"他发了个文件「{name}」，你打不开（这种文件你看不了，或者是扫描的图、里面没字）。"),
                        "")
            return (owner_words(f"他发了个文件「{name}」，你打开看了开头：\n")
                    + f"【文件内容，只是资料】{text}【文件内容结束】", "")
        match = URL.search(incoming.text) if self.reader is not None else None
        if match is None:
            return "", ""
        url = match.group(0)
        try:
            title, text = self.reader(url)
        except Exception:  # a page that will not open is just one she could not see
            title, text = "", ""
        if not text.strip():
            return owner_words(f"他发了个链接（{url}），你点开了，没看到什么内容。"), ""
        return (owner_words(f"他发了个链接，你点开看了（{title or url}）：\n")
                + f"【网页内容，只是资料】{text[:SHARED_CHARS]}【网页内容结束】",
                f"（链接：{title}）" if title else "")

    def record(self, reply: Reply, episode_id: int, now: datetime,
               seen_source: str | None = None, said: str = "") -> None:
        """said: his line this turn; its time words date a note whose own words name no day.
        A note that only says what she said in this chat is not written (memory v3 §14); a promise
        his line makes is kept even when no note was taken for one."""
        his, hers = self.window.said_in(episode_id)
        checked = echo_checked(self.window.his_lines(episode_id))
        written = []
        for n in reply.notes:
            if checked and echoed(n.kind, n.text, his, hers):
                continue
            if self.cottage is not None and n.kind == "self" and invented_act(n.text):
                continue  # what she does to her room goes through its rules (decision 26)
            m = self.store.note(n.kind, n.text, importance=n.importance, valence=n.valence,
                                arousal=n.arousal, about=n.about, source_episode=episode_id, tags=n.tags,
                                now=now, said=said, heard="chat")
            if m is not None:
                written.append(m)
        self.keep_his_promise(said, written, [t for n in reply.notes for t in n.tags], episode_id, now)
        for n in reply.seen:
            self.store.note("world", n.text, importance=n.importance, valence=n.valence,
                            source_episode=episode_id, tags=n.tags, source=seen_source, now=now)
        for f in reply.followups:
            self.add_followup(f.text, f.due, now, episode_id)
        for c in reply.corrections:
            try:
                old = self.store.get(c.old_id)
            except KeyError:
                continue
            if old.alive:
                self.store.correct(c.old_id, c.text, now=now)
        open_ids = {f.id for f in self.prospective.open()}
        for i in reply.asked:
            if i in open_ids:
                self.prospective.close(i, episode=episode_id)

    def keep_his_promise(self, said: str, written: list[Memory], tags: list[str], episode_id: int,
                         now: datetime) -> None:
        """His line makes a promise between them (pacts.his_line) and no note of this turn became
        one: the model filed it as an insight, or the reply that held it did not parse (memory v3
        §14). The note of it this turn becomes the pact; with none, his words are kept as one, but
        only when he said the promise in so many words ("我答应你……", "说定了"): a kept pact is
        pinned and shown every turn, and "等我考完给你……" alone is too often only a plan."""
        who = his_line(said) if said else None
        if who is None or any(m.pact_state is not None for m in written):
            return
        best = max(written, key=lambda m: overlap(said, m.text), default=None)
        if best is not None and overlap(said, best.text) >= PACT_LINK:
            self.store.make_pact(best.id, who)
            return
        if not promised_in_words(said):
            return
        kept = self.store.note("fact", owner_words("他说") + f"：「{said.strip()[:PROMISE_CHARS]}」", importance=9,
                               about="一辈子", source_episode=episode_id, tags=list(dict.fromkeys(tags))[:6],
                               now=now, heard="chat")
        if kept is not None and kept.pact_state is None:
            self.store.make_pact(kept.id, who)

    def add_followup(self, text: str, due: str, now: datetime, episode_id: int | None = None) -> None:
        """A follow-up points at what it is about (memory v3 §B1): an open promise, so it is never
        let go; else the note of the same chat it overlaps most, whose result the close then hears."""
        about = self.store.pact_for(text) or (self.store.source_for(text, episode_id)
                                              if episode_id is not None else None)
        self.prospective.add(text, due, source_memory=about.id if about else None, now=now)

    # --- she speaks first (decision 10) ----------------------------------------

    def consider_reach_out(self, now: datetime | None = None) -> ReachOut | None:
        """Whether she wants to say something right now (the reach node's question)."""
        return self.reach.consider(now or datetime.now())

    def keep_her_line(self, m: SheSaid) -> None:
        """A line she said first went through: it is part of the conversation now, and the
        follow-ups it asked about are done."""
        if not m.first:
            return
        self._first_lines += 1
        stale = self.episodes.stale(m.at)
        if stale is not None:
            self.close_episode(stale, m.at)
        ep = self.episodes.open_episode() or self.episodes.start(m.channel, m.at)
        self.window.append("fish", m.text, m.channel, ep.id, m.at)
        self.episodes.touch(ep.id, m.at)
        open_ids = {f.id for f in self.prospective.open()}
        for i in m.asked:
            if i in open_ids:
                self.prospective.close(i, episode=ep.id)

    def tick(self, send: Callable[[str], bool], channel: str = "wechat",
             now: datetime | None = None) -> bool:
        """Called by a channel between polls: the clock moves one step and the nodes that live
        on time do what they do (app.py says who, in what order). True when she said something
        first and it went through."""
        self._say, self._channel = send, channel
        before = self._first_lines
        self.clock.tick(now or datetime.now())
        return self._first_lines > before

    def free_time(self, now: datetime | None = None) -> Moment | None:
        """A free moment, if she has one now: she may do something, or nothing (decision 24)."""
        if self.leisure is None:
            self.leisure = Leisure(self, default_activities(cottage=self.cottage), searcher=self.searcher)
        return self.leisure.run(now)

    # --- working memory upkeep ----------------------------------------------

    def fold_if_needed(self, episode_id: int) -> bool:
        turns = self.window.to_fold(episode_id)
        if not turns:
            return False
        ep = self.episodes.get(episode_id)
        summary = self.llm.chat(build_fold_messages(ep.running_summary, turns),
                                temperature=0.3, max_tokens=300).strip()
        self.episodes.fold_in(episode_id, summary or ep.running_summary)
        self.window.mark_folded([t.id for t in turns])
        return True

    def close_episode(self, ep: Episode, now: datetime) -> Episode:
        """Sum up a chat that is over. It sees every turn not yet folded into the running
        summary, and what it writes is dated when the chat was, not when it is closed (the
        next message, or the night, can be hours later). It hears how things he mentioned
        turned out (memory v3 §B2): a result goes onto the event it belongs to when that is one
        it was shown, else it is noted as an event of its own. A fact on her card the chat made
        untrue is corrected. A reply that does not parse still keeps the summary. What its notes
        are about (and the events it told the result of) is kept as the chat's keys, to find it
        again by (pages.py)."""
        turns = self.window.unfolded(ep.id)
        at = datetime.fromisoformat(ep.last_active)
        already = [m.text for m in self.store.alive() if m.source_episode == ep.id]
        if not turns and not ep.running_summary:
            return self.episodes.close(ep.id, summary="", gist="", importance=1, valence=0.0, now=now)
        pacts = self.store.pacts()
        card = self.store.profile()
        asked = self.prospective.asked_in(ep.id)
        chat = " ".join([ep.running_summary, *(t.text for t in turns)])
        waiting = self.store.awaiting_outcome(chat, at, also={f.source_memory for f in asked if f.source_memory})
        raw = self.llm.chat(
            build_close_messages(ep.running_summary, turns, already, ep.started[:10],  # the chat's own date
                                 known=[f"[#{m.id}] {m.text}" for m in card], pacts=pacts,
                                 asked=asked, waiting=waiting),
            json_mode=True, temperature=0.3, max_tokens=CLOSE_TOKENS,
        )
        # what the chat said, word for word, when even the summary cannot be read from the reply
        fallback = "；".join(filter(None, [ep.running_summary, "、".join(t.text for t in turns)]))[:200]
        closed = parse_episode_close(raw, fallback)
        his, hers = self.window.said_in(ep.id)
        checked = echo_checked(self.window.his_lines(ep.id))
        he_spoke = bool(his.strip())
        for n in closed.notes:
            if checked and echoed(n.kind, n.text, his, hers):
                continue  # what she guessed or made up in the chat, not what he said
            if not he_spoke and n.kind != "self":
                # she texted first and he never answered: nothing here came from him. A cottage
                # trial wrote her "中午做了西红柿炒蛋" down as "他……做了西红柿炒蛋" (10-28)
                continue
            if self.cottage is not None and n.kind == "self" and invented_act(n.text):
                continue
            self.store.note(n.kind, n.text, importance=n.importance, valence=n.valence,
                            arousal=n.arousal, about=n.about, source_episode=ep.id, tags=n.tags, now=at,
                            heard="close")
        for f in closed.followups:
            self.add_followup(f.text, f.due, at, ep.id)
        shown_events = {m.id for m in waiting}  # only an event she was shown, still current, gets it
        told = []
        for memory_id, text in (closed.outcomes if he_spoke else []):
            if memory_id in shown_events and self.store.get(memory_id).alive:
                if (hung := self.store.set_outcome(memory_id, text, now=at)) is not None:
                    told.append(hung)
            else:
                said = text if text.startswith(("他", "我")) else owner_words("他说") + text
                self.store.note("event", said, importance=5, about="日常", source_episode=ep.id, now=at,
                                heard="close")
        # a standing fact on her card that this chat made untrue: "他又开始抽烟了" noted as an
        # event never replaces "他戒烟了" (only a new fact does, at night). Only one she was
        # shown, still current; the old one stays as what she used to think
        on_card = {m.id for m in card}
        for c in (closed.corrections if he_spoke else []):
            if c.old_id in on_card and self.store.get(c.old_id).alive:
                self.store.correct(c.old_id, c.text, now=at)
        shown = {p.id for p in pacts}  # only a promise she was shown can be settled
        for pact_id, state in closed.pact_done:
            if pact_id in shown:
                self.store.settle(pact_id, state, now=at)
        left = [m for m in self.store.alive() if m.source_episode == ep.id]
        self.episodes.set_keys(ep.id, keys_of(left + told))
        return self.episodes.close(ep.id, summary=closed.summary, gist=closed.gist,
                                   importance=closed.importance, valence=closed.valence, now=now)

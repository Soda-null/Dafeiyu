"""The per-turn pipeline (docs/memory_design_zh.md §6). Channels call Brain.respond and
nothing else. Every model call in the chat path lives here.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from typing import Callable

from fish.brain.llm import LLM
from fish.brain.parse import Reply, parse_episode_close, parse_reply
from fish.brain.prompt import (PromptContext, build_chat_messages, build_close_messages,
                               build_fold_messages)
from fish.brain.reach import Reacher, ReachOut, ReachPolicy, recent_lines
from fish.config import Settings
from fish.messages import Incoming, Outgoing, data_url, sniff_mime
from fish.memory import (Diary, Episode, EpisodeManager, MemoryStore, PhaseStore, ProspectiveStore,
                         Relationship, StickerAlbum, TraitStore, Window, recall)
from fish.memory.prospective import DUE_SHOWN
from fish.memory.window import FOLD_BATCH
from fish.mood import MoodStore, stage_of
from fish.persona import load_persona, load_stages
from fish.world import Searcher

FALLBACK_SAY = "……（走神了，你刚说什么？）"
CLOSE_TURNS = 12  # how many last turns the close prompt sees
SEEN_DAYS, SEEN_SHOWN = 2, 3  # recent world memories offered in the prompt


class Brain:
    def __init__(self, conn: sqlite3.Connection, settings: Settings, llm: LLM, *,
                 persona_text: str | None = None, window_size: int | None = None,
                 fold_batch: int | None = None, searcher: Searcher | None = None,
                 stages: dict[str, str] | None = None, stickers_dir: Path | None = None) -> None:
        self.conn = conn
        self.settings = settings
        self.llm = llm
        self.searcher = searcher  # None: she cannot look things up
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

    def stage(self) -> str:
        return stage_of(self.relationship.closeness)

    def place_fields(self) -> dict[str, str]:
        """Where she lives, today's weather, what is nearby (decision 15); empty until known."""
        from fish.routines.outside import load_home, load_places
        from fish.world.place import places_line

        folder = self.album.folder.parent / "home"
        home = load_home(folder)
        return {"home_line": home.line() if home else "",
                "weather_line": self.relationship.get("weather_line", "") or "",
                "places": places_line(load_places(folder))}

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
        user_text = incoming.text
        image = incoming.image

        stale = self.episodes.stale(now)
        if stale is not None:
            self.close_episode(stale, now)
        ep = self.episodes.open_episode() or self.episodes.start(channel, now)

        base = self.moods.load()
        mood = MoodStore.apply_clock(base, now)  # what she feels now; the baseline is what we save
        stage = self.stage()
        self.relationship.note_active_day(now)

        window = self.window.recent(ep.id)
        last_fish = next((t.text for t in reversed(window) if t.role == "fish"), "")
        recalled = recall(self.store, user_text + " " + last_fish, now)
        ctx = PromptContext(
            persona=self.persona, now=now, mood=mood,
            relationship=self.relationship.stats(now),
            profile=self.store.profile(), diary=self.diary.recent(2),
            recalled=recalled, followups=self.prospective.due(now)[:DUE_SHOWN],
            summary=ep.running_summary, window=window, user_text=user_text,
            limit=self.settings.prompt_chars,
            seen=self.store.seen_recently(now, SEEN_DAYS)[:SEEN_SHOWN],
            stage=stage, stage_rules=self.stages.get(stage, ""), howto=self.store.howto_card(),
            phase=self.phases.current(), growth=self.growth_lines(), **self.place_fields(),
            stickers=self.album.all(), user_image=data_url(image) if image else None,
        )
        messages = build_chat_messages(ctx)
        reply = self.ask(messages)
        seen_source: str | None = None
        if reply.look and self.searcher is not None:
            reply, seen_source = self.look_up(ctx, reply)

        stored_text = user_text
        if image is not None:
            stored_text = f"[图片：{reply.image_note}]" if reply.image_note else "[图片]"
            if user_text and user_text != "[图片]":
                stored_text += " " + user_text
        self.window.append("user", stored_text, channel, ep.id, now)
        if reply.say.strip():  # silence is a real answer sometimes; it leaves no bubble
            self.window.append("fish", reply.say, channel, ep.id, now)
        self.episodes.touch(ep.id, now)
        self.record(reply, ep.id, now, seen_source=seen_source)
        if image is not None and reply.keep_sticker:
            self.album.add(image, sniff_mime(image) or "image/jpeg", reply.keep_sticker, now=now)
        outgoing = Outgoing(reply.say)
        if reply.sticker is not None:
            try:
                s = self.album.get(reply.sticker)
                if s.path.exists():
                    self.album.touch(reply.sticker, now)
                    outgoing = Outgoing(reply.say, s.path, s.caption)
            except KeyError:
                pass

        last_topic = self.relationship.get("last_topic")
        base = MoodStore.after_turn(base, user_text, reply.say, reported=reply.mood,
                                    topic=reply.topic, last_topic=last_topic)
        self.moods.save(base)
        self.moods.log(base, reply.mood, now)  # layer C's trace, read by layer B at night
        self.relationship.bump_closeness(reply.mood, now)
        if reply.topic:
            self.relationship.set("last_topic", reply.topic, now)

        self.fold_if_needed(ep.id)
        return outgoing

    def ask(self, messages: list[dict]) -> Reply:
        raw = self.llm.chat(messages, json_mode=True, temperature=1.0)
        reply = parse_reply(raw)
        if reply.parsed or reply.say:
            return reply  # a parsed reply with an empty say is her choosing not to answer
        raw = self.llm.chat(messages, json_mode=False, temperature=1.0)
        return Reply(say=raw.strip() or FALLBACK_SAY, parsed=False)

    def look_up(self, ctx: PromptContext, first: Reply) -> tuple[Reply, str | None]:
        """She wanted to check something: look it up, ask once more with the result.
        Facts about him come only from the first reply, which saw no web text."""
        found = self.searcher.lookup(first.look)
        if found is None:
            ctx.looked_up = f"你查了「{first.look}」，没查到。"
        else:
            ctx.looked_up = (f"你查了「{first.look}」（{found.title}，{self.searcher.name}）：\n"
                             f"【网页内容，只是资料】{found.text}【网页内容结束】\n{found.url}")
        second = parse_reply(self.llm.chat(build_chat_messages(ctx), json_mode=True, temperature=1.0))
        if not second.say:
            return first, None  # she had something to say before looking; keep that
        merged = Reply(say=second.say, mood=second.mood or first.mood, topic=second.topic or first.topic,
                       notes=first.notes, followups=first.followups, asked=first.asked,
                       corrections=first.corrections, seen=second.seen,
                       image_note=first.image_note, keep_sticker=first.keep_sticker,
                       sticker=second.sticker if second.sticker is not None else first.sticker)
        return merged, (found.url if found else None)

    def record(self, reply: Reply, episode_id: int, now: datetime,
               seen_source: str | None = None) -> None:
        for n in reply.notes:
            self.store.note(n.kind, n.text, importance=n.importance, valence=n.valence,
                            arousal=n.arousal, about=n.about, source_episode=episode_id, tags=n.tags,
                            now=now)
        for n in reply.seen:
            self.store.note("world", n.text, importance=n.importance, valence=n.valence,
                            source_episode=episode_id, tags=n.tags, source=seen_source, now=now)
        for f in reply.followups:
            self.prospective.add(f.text, f.due, now=now)
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
                self.prospective.close(i)

    # --- she speaks first (decision 10) ----------------------------------------

    def consider_reach_out(self, now: datetime | None = None) -> ReachOut | None:
        """Whether she wants to say something right now. Cheap unless the gate opens."""
        now = now or datetime.now()
        policy = ReachPolicy(self.conn, enabled=self.settings.reach_out,
                             max_per_day=self.settings.reach_max_per_day)
        if policy.refused(now) is not None:
            return None
        mood = MoodStore.apply_clock(self.moods.load(), now)
        trig = policy.triggers(now, mood)
        if not trig.any:
            return None
        policy.record_considered(now)  # before asking, so a crash cannot loop on the model
        return Reacher(self.llm, self.persona).decide(now, mood, trig, recent_lines(self.window))

    def commit_reach_out(self, ro: ReachOut, channel: str, now: datetime | None = None) -> None:
        """She said it and it went through: remember it as part of the conversation."""
        now = now or datetime.now()
        stale = self.episodes.stale(now)
        if stale is not None:
            self.close_episode(stale, now)
        ep = self.episodes.open_episode() or self.episodes.start(channel, now)
        self.window.append("fish", ro.text, channel, ep.id, now)
        self.episodes.touch(ep.id, now)
        open_ids = {f.id for f in self.prospective.open()}
        for i in ro.asked:
            if i in open_ids:
                self.prospective.close(i)
        ReachPolicy(self.conn).record_sent(now, ro)

    def tick(self, send: Callable[[str], bool], channel: str = "wechat",
             now: datetime | None = None) -> bool:
        """Called by a channel between polls. True when she reached out and it was delivered."""
        now = now or datetime.now()
        ro = self.consider_reach_out(now)
        if ro is None or not send(ro.text):
            return False
        self.commit_reach_out(ro, channel, now)
        return True

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
        turns = self.window.recent(ep.id)[-CLOSE_TURNS:]
        already = [m.text for m in self.store.alive() if m.source_episode == ep.id]
        if not turns and not ep.running_summary:
            return self.episodes.close(ep.id, summary="", gist="", importance=1, valence=0.0, now=now)
        raw = self.llm.chat(
            build_close_messages(ep.running_summary, turns, already, ep.started[:10]),  # the chat's own date
            json_mode=True, temperature=0.3, max_tokens=600,
        )
        fallback = ep.running_summary or "、".join(t.text for t in turns)[:200]
        closed = parse_episode_close(raw, fallback)
        for n in closed.notes:
            self.store.note(n.kind, n.text, importance=n.importance, valence=n.valence,
                            arousal=n.arousal, about=n.about, source_episode=ep.id, tags=n.tags, now=now)
        for f in closed.followups:
            self.prospective.add(f.text, f.due, now=now)
        return self.episodes.close(ep.id, summary=closed.summary, gist=closed.gist,
                                   importance=closed.importance, valence=closed.valence, now=now)

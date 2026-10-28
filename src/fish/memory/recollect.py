"""What his line brings to her mind: the memory node's answer for one chat turn
(docs/nodes_design_zh.md, step 2). The brain gets this and nothing else from memory.

Her card and the promises are in front of her anyway; a card fact his line touches is marked
and used but grows no stronger (memory v3 §B3, §B4). What his line recalls skips them. When he
asks her to remember or names a day she may look back at old chats' summaries (pages.py, the
FISH_PAGES switch). The order below is the order of the writes (touching, recalling): keep it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from fish.memory.daychat import DayChat, day_chat
from fish.memory.diary import Diary
from fish.memory.episodes import Episode, EpisodeManager
from fish.memory.longterm import Memory, MemoryStore
from fish.memory.pacts import asks_pact, triggered
from fish.memory.pages import Page, asks_recall, may_answer, turn_back
from fish.memory.patterns import arrival_line, asks_habit
from fish.memory.phase import Phase, PhaseStore
from fish.memory.prospective import DUE_SHOWN, Followup, ProspectiveStore
from fish.memory.relationship import Relationship
from fish.memory.retrieval import TOUCH_RELEVANCE, BigramEmbedder, Recalled, cue_for, mentioned, recall
from fish.memory.today import section as today_section
from fish.memory.when import TimeCued
from fish.memory.window import Window

SEEN_DAYS, SEEN_SHOWN = 2, 3  # recent world memories offered in the prompt
DIARY_SHOWN = 2


@dataclass
class Recollection:
    profile: list[Memory]  # her card
    touched: list[Memory]  # card facts his line touches
    formers: dict[int, str]  # card fact id -> what she used to think
    pacts: list[Memory]  # promises between them (settled ones too when he asks)
    stars: dict[int, str]  # pact id -> the trigger his line said
    recalled: list[Recalled]  # what his line brought back
    pages: list[Page]  # old chats she looked back at
    today: str  # the "today" section, worked out by code
    nothing_found: bool  # he asks if she remembers and nothing came back (memory v3 §14)
    followups: list[Followup]  # due today
    seen: list[Memory]  # what she saw online lately
    howto: list[Memory]  # how to get along with him
    diary: list[tuple[str, str]]
    phase: Phase
    day: DayChat  # today's chat (decision 32)


class Recollector:
    """Holds the memory node's stores; the brain owns none of them for this."""

    def __init__(self, conn: sqlite3.Connection, *, store: MemoryStore, prospective: ProspectiveStore,
                 episodes: EpisodeManager, window: Window, diary: Diary, phases: PhaseStore,
                 relationship: Relationship) -> None:
        self.conn = conn
        self.store = store
        self.prospective = prospective
        self.episodes = episodes
        self.window = window
        self.diary = diary
        self.phases = phases
        self.relationship = relationship

    def today_lines(self, now: datetime, profile: list[Memory], said: str = "", him: str = "他") -> str:
        """Dates, his birthday soon, what he planned for today and tomorrow, what he does on
        this weekday (counted at night) and when he usually comes (memory v3 §B3, §B6). His line
        asking what he usually does shows every pattern."""
        plans = self.store.planned_for([now.date(), now.date() + timedelta(days=1)])
        return today_section(now, profile, plans, patterns=self.relationship.patterns(),
                             arrival=arrival_line(self.conn, now), asked=asks_habit(said), him=him)

    def recollect(self, said: str, ep: Episode, now: datetime, *, pages: bool = True,
                  him: str = "他") -> Recollection:
        day = day_chat(self.window, self.episodes, ep, now)
        last_fish = next((t.text for t in reversed(day.current) if t.role == "fish"), "")
        profile = self.store.profile()
        touched = mentioned(said, profile)
        for m in touched:
            self.store.touch(m.id, now, strengthen=False)
        formers = {m.id: f.text for m in profile if (f := self.store.former(m.id)) is not None}
        # he asks her to remember something: the promises kept or called off are shown too, since
        # "我跟你立过一个flag" names none of the promise words (10-28 checkups)
        pacts = self.store.pacts(settled=asks_pact(said) or asks_recall(said))
        stars = triggered(said, [p for p in pacts if p.pact_state == "open"])
        cue = cue_for(said, last_fish)
        recalled = recall(self.store, cue, now, embedder=TimeCued(BigramEmbedder(), now),
                          skip={m.id for m in profile + pacts})
        found_pages = turn_back(self.episodes.closed(), said, now, cue=cue, skip={ep.id}) if pages else []
        today = self.today_lines(now, profile, said, him)
        # nothing his line touches came back: no memory she was reminded of is close to his line
        # or shares a word with what he asks about
        nothing_found = (asks_recall(said) and not found_pages and not touched and not stars
                         and not (pacts and asks_pact(said))  # the answer is in that block
                         and not any(r.relevance >= TOUCH_RELEVANCE or may_answer(said, r.memory.text)
                                     for r in recalled))
        return Recollection(
            profile=profile, touched=touched, formers=formers, pacts=pacts, stars=stars,
            recalled=recalled, pages=found_pages, today=today, nothing_found=nothing_found,
            followups=self.prospective.due(now)[:DUE_SHOWN],
            seen=self.store.seen_recently(now, SEEN_DAYS)[:SEEN_SHOWN],
            howto=self.store.howto_card(), diary=self.diary.recent(DIARY_SHOWN),
            phase=self.phases.current(), day=day,
        )

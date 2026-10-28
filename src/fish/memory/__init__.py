"""Her memory: data and math only, no model calls (docs/memory_design_zh.md §8, rule 4).

window      the last turns, verbatim (working memory)
episodes    one record per chat session
longterm    the `memories` table: facts, events, how-to-get-along, insights, her own life
stability   the forgetting math
retrieval   which memories a line brings to mind
when        recall by time: memories from the days a line names; the day a note is about
today       the "today" section: dates of this week and next, birthday soon, plans for today
prospective things she means to ask him on a given day
diary       her own day, one entry each
relationship when they met, days talked, streak
pastimes    what she follows in her free time (a book), and the free-moment log

Never depends on the channels package.
"""

from fish.memory.diary import Diary
from fish.memory.episodes import Episode, EpisodeManager
from fish.memory.longterm import KINDS, Memory, MemoryStore, overlap
from fish.memory.pastimes import Moment, Pastime, Pastimes
from fish.memory.phase import Phase, PhaseStore
from fish.memory.prospective import Followup, ProspectiveStore
from fish.memory.relationship import Relationship
from fish.memory.retrieval import BigramEmbedder, Embedder, Recalled, cue_for, mentioned, recall
from fish.memory.stickers import Sticker, StickerAlbum
from fish.memory.today import section as today_section
from fish.memory.traits import TRAITS, Growth, TraitStore
from fish.memory.when import TimeCued
from fish.memory.window import Turn, Window

__all__ = [
    "KINDS", "TRAITS", "BigramEmbedder", "Diary", "Embedder", "Episode", "EpisodeManager",
    "Followup", "Growth", "Memory", "MemoryStore", "Moment", "Pastime", "Pastimes", "Phase", "PhaseStore", "ProspectiveStore",
    "Recalled", "Relationship", "Sticker", "StickerAlbum", "TimeCued", "TraitStore", "Turn", "Window",
    "cue_for", "mentioned", "overlap", "recall", "today_section",
]

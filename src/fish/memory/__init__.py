"""Her memory: data and math only, no model calls (docs/memory_design_zh.md §8, rule 4).

window      the last turns, verbatim (working memory)
episodes    one record per chat session
longterm    the `memories` table: facts, events, how-to-get-along, insights, her own life
stability   the forgetting math
retrieval   which memories a line brings to mind
when        recall by time: memories from the days a line names; the day a note is about
pacts       promises between them and his nickname for her, found by fixed words
pages       turning back to old chats' summaries when he asks her to remember (never his messages)
today       the "today" section: dates of this week and next, birthday soon, plans for today
patterns    what he says on one weekday, counted at night; when he usually comes
prospective things she means to ask him on a given day
scrub       secrets (codes, passwords) never written: refused in notes, cut from summaries and diary
diary       her own day, one entry each
daychat     today's chat as she holds it: earlier chats word for word, this one whole (decision 32)
recollect   what his line brings to her mind: the one answer the brain gets from memory per turn
relationship when they met, days talked, streak
pastimes    what she follows in her free time (a book), and the free-moment log

Never depends on the channels package.
"""

from fish.memory.daychat import DAY_LIMIT, Block, DayChat, day_chat
from fish.memory.daychat import fit as fit_day_chat
from fish.memory.diary import Diary
from fish.memory.episodes import Episode, EpisodeManager
from fish.memory.longterm import ABOUT_HIM_KINDS, KINDS, PACT_LINK, Memory, MemoryStore, echoes_her, iso, overlap
from fish.memory.pastimes import Moment, Pastime, Pastimes
from fish.memory.phase import Phase, PhaseStore
from fish.memory.pacts import asks_pact, his_line, promised_in_words, triggered
from fish.memory.pages import Page, asks_recall, keys_of, may_answer, turn_back
from fish.memory.patterns import arrival_line, asks_habit, count_patterns
from fish.memory.prospective import DUE_SHOWN, Followup, ProspectiveStore
from fish.memory.recollect import Recollection, Recollector
from fish.memory.relationship import Relationship
from fish.memory.retrieval import BigramEmbedder, Embedder, Recalled, cue_for, mentioned, recall
from fish.memory.scrub import redact, secret
from fish.memory.stickers import Sticker, StickerAlbum
from fish.memory.today import section as today_section
from fish.memory.traits import TRAITS, Growth, TraitStore
from fish.memory.when import TimeCued, spoken, told_day
from fish.memory.window import FOLD_BATCH, Turn, Window, first_message_at, he_wrote_between, last_his_message

__all__ = [
    "ABOUT_HIM_KINDS", "DAY_LIMIT", "DUE_SHOWN", "FOLD_BATCH", "KINDS", "PACT_LINK", "TRAITS", "BigramEmbedder", "Block", "DayChat",
    "Diary", "Recollection", "Recollector", "day_chat", "first_message_at", "fit_day_chat", "he_wrote_between",
    "last_his_message", "Embedder", "Episode", "EpisodeManager",
    "Followup", "Growth", "Memory", "MemoryStore", "Moment", "Page", "Pastime", "Pastimes", "Phase", "PhaseStore", "ProspectiveStore",
    "Recalled", "Relationship", "Sticker", "StickerAlbum", "TimeCued", "TraitStore", "Turn", "Window",
    "arrival_line", "asks_habit", "asks_pact", "asks_recall", "echoes_her", "his_line", "iso", "count_patterns", "cue_for", "keys_of", "may_answer", "mentioned", "overlap", "promised_in_words", "recall", "redact", "secret", "spoken", "today_section", "told_day",
    "triggered", "turn_back",
]

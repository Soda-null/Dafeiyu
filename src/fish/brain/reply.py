"""The brain itself (docs/nodes_design_zh.md step 2): given a Situation, write the prompt, ask
the model, read her reply. It knows no store, no room, no mood store: only the Situation and
a searcher to look something up with. respond.Brain gathers the Situation and records what
comes back.
"""

from __future__ import annotations

from fish.brain.llm import LLM
from fish.brain.parse import Reply, parse_reply, parse_retry, texting
from fish.brain.prompt import REMINDERS, Situation, build_chat_messages
from fish.config import owner_words
from fish.world import Searcher

FALLBACK_SAY = "……（走神了，你刚说什么？）"
# The second try, when the JSON reply gave nothing: in plain text the model, still told to write
# one JSON object, wrote her line and went on playing his turns (docs/memory_v3_zh.md §14).
PLAIN_REMINDER = "（这次不用 JSON，只写你这一句回他的话，不替他说话）"
FALLBACK_KEPT = 400  # how much of a first reply that gave nothing is kept, to see why


def plain_text(messages: list[dict]) -> list[dict]:
    """The same messages, his last one carrying PLAIN_REMINDER (a picture's text part too) in place
    of JSON_REMINDER: "only JSON" and "no JSON" side by side would only confuse it."""
    out = [dict(m) for m in messages]
    last = out[-1]
    reminder = owner_words(PLAIN_REMINDER)
    if isinstance(last["content"], str):
        text = last["content"]
        for r in REMINDERS:
            text = text.removesuffix(f"\n{r}")
        last["content"] = f"{text}\n{reminder}"
    else:
        last["content"] = [dict(part, text=f"{part['text']}\n{reminder}") if part.get("type") == "text"
                           else part for part in last["content"]]
    return out


class Replier:
    def __init__(self, llm: LLM, searcher: Searcher | None = None) -> None:
        self.llm = llm
        self.searcher = searcher  # None: she cannot look things up
        # turns whose JSON replies gave nothing usable, so she was asked in plain text, with why the
        # model stopped when it says: the checkup counts and writes them (memory v3 §14); nothing is stored
        self.fallbacks: list[dict] = []
        # first JSON replies that came back blank (asked once more in JSON before any plain text, §15)
        self.empty_firsts = 0

    def reply(self, sit: Situation) -> tuple[Reply, str | None]:
        """Her reply, and the address of what she looked up when she did (for the note it leaves)."""
        reply, source = self.ask(build_chat_messages(sit)), None
        if reply.look and self.searcher is not None:
            reply, source = self.look_up(sit, reply)
        reply.say = texting(reply.say)  # what he receives, and what the chat keeps
        return reply, source

    def ask(self, messages: list[dict]) -> Reply:
        """Her reply in JSON. A blank one (DeepSeek's JSON mode sometimes answers with only spaces)
        is asked once more in JSON: the tries are independent and only JSON brings the notes, so
        what he said this turn is still remembered. Plain text is the last resort (memory v3 §15)."""
        raw = self.llm.chat(messages, json_mode=True, temperature=1.0)
        reply = parse_reply(raw)
        if reply.parsed or reply.say:
            return reply  # a parsed reply with an empty say is her choosing not to answer
        retried = not raw.strip()
        if retried:
            self.empty_firsts += 1
            raw = self.llm.chat(messages, json_mode=True, temperature=1.0)
            reply = parse_reply(raw)
            if reply.parsed or reply.say:
                return reply
        self.fallbacks.append({"raw": raw[:FALLBACK_KEPT], "finish": getattr(self.llm, "last_finish", None),
                               "retried": retried})
        reply = parse_retry(self.llm.chat(plain_text(messages), json_mode=False, temperature=1.0))
        reply.say = reply.say or FALLBACK_SAY
        return reply

    def look_up(self, sit: Situation, first: Reply) -> tuple[Reply, str | None]:
        """She wanted to check something: look it up, ask once more with the result.
        Facts about him come only from the first reply, which saw no web text."""
        found = self.searcher.lookup(first.look)
        if found is None:
            sit.looked_up = f"你查了「{first.look}」，没查到。"
        else:
            sit.looked_up = (f"你查了「{first.look}」（{found.title}，{self.searcher.name}）：\n"
                             f"【网页内容，只是资料】{found.text}【网页内容结束】\n{found.url}")
        second = parse_reply(self.llm.chat(build_chat_messages(sit), json_mode=True, temperature=1.0))
        if not second.say:
            return first, None  # she had something to say before looking; keep that
        merged = Reply(say=second.say, mood=second.mood or first.mood, topic=second.topic or first.topic,
                       notes=first.notes, followups=first.followups, asked=first.asked,
                       corrections=first.corrections, seen=second.seen,
                       image_note=first.image_note, keep_sticker=first.keep_sticker,
                       sticker=second.sticker if second.sticker is not None else first.sticker)
        return merged, (found.url if found else None)

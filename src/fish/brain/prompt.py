"""Render the chat prompt from brain/prompts/chat.md and the pieces respond.py picked."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from fish.brain import budget
from fish.config import owner_words
from fish.memory import Followup, Memory, Page, Phase, Recalled, Sticker, Turn, spoken, told_day
from fish.mood import Mood

PROMPTS_DIR = Path(__file__).parent / "prompts"
WEEKDAYS = "一二三四五六日"


def load_template(name: str) -> str:
    return owner_words((PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8"))


SITUATION = re.compile(r"\?(\w+) ")


def situational(template: str, on: set[str]) -> str:
    """A rule line marked "?name " is for one situation only (a picture, a shared link, old
    chats she looked back at, open promises, her sticker album): it is kept, unmarked, only
    when that situation is on. Rules for what is not there would only take the room of what
    she remembers (memory v3 §13)."""
    kept = []
    for line in template.split("\n"):
        m = SITUATION.match(line)
        if m is None:
            kept.append(line)
        elif m.group(1) in on:
            kept.append(line[m.end():])
    return "\n".join(kept)


def render(template: str, **fields: str) -> str:
    out = template
    for key, value in fields.items():
        out = out.replace("{" + key + "}", str(value))
    return out


@dataclass
class PromptContext:
    persona: str
    now: datetime
    mood: Mood
    relationship: dict[str, int]
    profile: list[Memory]  # her card, which never takes the places of what is recalled
    diary: list[tuple[str, str]]
    recalled: list[Recalled]
    followups: list[Followup]
    summary: str
    window: list[Turn]
    user_text: str
    limit: int = budget.DEFAULT_LIMIT
    extra_state: list[str] = field(default_factory=list)
    seen: list[Memory] = field(default_factory=list)  # world memories from the last days
    looked_up: str = ""  # what a `look` in this turn found
    stage: str = "刚认识"  # closeness stage (relationship layer)
    stage_rules: str = ""  # how she talks at the current closeness stage (persona file)
    howto: list[Memory] = field(default_factory=list)  # the rules she drew for getting along
    phase: Phase | None = None  # layer B: how she has been these days
    home_line: str = ""  # where she lives, city and neighbourhood (decision 15)
    weather_line: str = ""  # today's weather there
    places: str = ""  # nearby places, names and walking minutes
    day_line: str = ""  # solar term, holiday (decision 24)
    pastimes_line: str = ""  # the book she is reading
    today_line: str = ""  # what she did with her free moments today
    growth: list[str] = field(default_factory=list)  # layer A: how she has changed from her origin
    stickers: list[Sticker] = field(default_factory=list)  # her album, for picking one
    user_image: str | None = None  # data URL of a picture he sent with this message
    shared: str = ""  # a link or file he shared, already opened (decision 23)
    mentioned: set[int] = field(default_factory=set)  # card facts his line touches
    formers: dict[int, str] = field(default_factory=dict)  # card fact id -> what she used to think
    today_section: str = ""  # dates, birthday soon, plans for today (memory/today.py)
    pacts: list[Memory] = field(default_factory=list)  # promises between them still open
    stars: dict[int, str] = field(default_factory=dict)  # pact id -> the trigger his line said
    nothing_found: bool = False  # he asks if she remembers and nothing came back (memory v3 §14)
    pages: list[Page] = field(default_factory=list)  # old chats she looked back at (memory/pages.py)


def state_line(ctx: PromptContext) -> str:
    now = ctx.now
    when = f"现在是 {now.strftime('%Y-%m-%d')} 周{WEEKDAYS[now.weekday()]} {now.strftime('%H:%M')}。"
    rel = ctx.relationship
    known = (f"你们认识第 {rel['days_known']} 天，聊过 {rel['days_talked']} 天"
             + (f"，连着 {rel['streak']} 天。" if rel.get("streak", 0) > 1 else "。"))
    parts = [when, known]
    if ctx.weather_line:
        parts.append(f"你那儿{ctx.weather_line}。")
    parts += [x for x in (ctx.day_line, ctx.pastimes_line, ctx.today_line) if x]
    parts.append(f"你此刻的状态：{ctx.mood.describe(ctx.stage)}。")
    return " ".join(parts + ctx.extra_state)


def render_phase(phase: Phase | None) -> str:
    if phase is None or not (phase.line or phase.day):
        return "（刚开始，还说不上）"
    bits = [phase.line] if phase.line else []
    bits.append(f"心情基调{phase.tone_word}，劲头{phase.drive_word}")
    if phase.focus:
        bits.append("这阵子在意的：" + "、".join(phase.focus))
    return "；".join(bits) + "。"


def render_growth(growth: list[str]) -> str:
    return "\n".join(f"- {g}" for g in growth) or "（还是刚认识时的样子）"


def render_howto(howto: list[Memory]) -> str:
    return "\n".join(f"- [#{m.id}] {m.line()}" for m in howto) or "（还在摸索）"


def render_stickers(stickers: list[Sticker]) -> str:
    return "\n".join(f"- [#{s.id}] {s.caption}" for s in stickers) or \
        "（相册还是空的：别填 sticker；他要表情包，就实话说没有、让他发几个给你）"


def render_profile(profile: list[Memory], mentioned: set[int] = frozenset(),
                   formers: dict[int, str] | None = None) -> str:
    """formers: what she used to think before a correction or update; the card is where the
    corrected facts about him live, so it shows them as recall does."""
    formers = formers or {}
    lines = []
    for m in profile:
        lines.append(f"- [#{m.id}] {m.line()}" + ("（他这句话提到了）" if m.id in mentioned else ""))
        if m.id in formers:
            lines.append(f"  （你之前记的是：{formers[m.id]}）")
    return "\n".join(lines) or "（还没有）"


# Checkup round two (memory v3 §14): asked "我新家有啥毛病来着" with nothing recalled, she went along
# with the question and named two faults he never had; the close then wrote them down as his.
NOTHING_FOUND = ("（这件你什么也没想起来：答案要是也不在“你一直记得的”里，就直说忘了、让他提醒你；"
                 "别说任何具体的东西，也别顺着他问法里的说法往下编）")

PACT_SAYS = {"him": "他答应过你", "her": "你答应过他", "both": "你们说好的"}


def render_pacts(pacts: list[Memory], stars: dict[int, str] | None = None) -> str:
    """The promises still open, one line each; one whose trigger his line just said comes
    first with a star: "★他刚说到「驾照」——你答应过他：……" (memory v3 §B3)."""
    stars = stars or {}
    lines = []
    for p in sorted(pacts, key=lambda p: p.id not in stars):
        # a kept one is shown when he asks what was promised: "……（兑现了）"
        says = owner_words(PACT_SAYS.get(p.pact or "", PACT_SAYS["both"])) + \
            f"：{p.text if p.pact_state in (None, 'open') else p.line()}"
        if p.id in stars:
            lines.append(f"- ★[#{p.id}] " + owner_words("他刚说到") + f"「{stars[p.id]}」——{says}")
        else:
            lines.append(f"- [#{p.id}] {says}")
    return "\n".join(lines) or "（没有）"


def day_label(m: Memory, today: date | None) -> str:
    """"（上周三 1月13日）": the day it happened, said the way he would say it (memory v3 §B3).
    None when nothing names its day: the day it was written would mislead her."""
    day = told_day(m) if today else None
    return f"（{spoken(day, today)}）" if day else ""


def render_recalled(recalled: list[Recalled], today: date | None = None) -> str:
    """today: when given, each line starts with the day it happened, relative to today."""
    lines = []
    former_shown = False
    for r in recalled:
        tag = "（模糊）" if r.fuzzy else ""
        tag += "（被提醒才想起）" if r.cued else ""
        lines.append(f"- [#{r.memory.id}] {day_label(r.memory, today)}{r.memory.line()}{tag}")
        if r.former and not former_shown:
            lines.append(f"  （你之前记的是：{r.former.text}）")
            former_shown = True
    return "\n".join(lines) or "（什么也没想起来。他要是问你记不记得，答案又不在你一直记得的那些里，那就是不记得了）"


def render_pages(pages: list[Page], today: date) -> str:
    """What is left of the chats she looked back at, each marked as the gist of that chat and
    not his words: "【那次聊天的大意，上周五 1月8日，不是原话】……" (memory v3 §B3)."""
    lines = []
    for p in pages:
        what = "只剩一句的大意" if p.gist_only else "大意"
        lines.append(f"- 【那次聊天的{what}，{spoken(p.day, today)}，不是原话】{p.text}")
    return "\n".join(lines) or "（没翻）"


def render_followups(followups: list[Followup]) -> str:
    return "\n".join(f"- [#{f.id}] {f.text}（{f.due} 到的）" for f in followups) or "（没有）"


def render_diary(diary: list[tuple[str, str]]) -> str:
    return "\n".join(f"- {day}：{text}" for day, text in diary) or "（还没写过）"


def render_seen(seen: list[Memory]) -> str:
    return "\n".join(f"- [#{m.id}] {m.text}" + (f"（{m.created[:10]}）" if m.created else "")
                     for m in seen) or "（最近没逛）"


def build_chat_messages(ctx: PromptContext) -> list[dict[str, str]]:
    on = {name for name, there in (("picture", ctx.user_image), ("shared", ctx.shared),
                                   ("pages", ctx.pages), ("pacts", ctx.pacts),
                                   ("stickers", ctx.stickers)) if there}
    template = situational(load_template("chat"), on)
    fixed_fields = dict(
        persona=ctx.persona, profile=render_profile(ctx.profile, ctx.mentioned, ctx.formers),
        diary=render_diary(ctx.diary),
        state=state_line(ctx), seen=render_seen(ctx.seen), looked_up=ctx.looked_up or "（没查）",
        stage=ctx.stage, stage_rules=ctx.stage_rules or "（照平时）",
        howto=render_howto(ctx.howto), stickers=render_stickers(ctx.stickers),
        phase=render_phase(ctx.phase), growth=render_growth(ctx.growth),
        home=(ctx.home_line + "。" if ctx.home_line else "（还不知道）")
        + (f"附近：{ctx.places}" if ctx.places else ""),
        shared=ctx.shared or "（没有）", today=ctx.today_section or "（没算）",
        pacts=render_pacts(ctx.pacts, ctx.stars), pages=render_pages(ctx.pages, ctx.now.date()),
    )
    today = ctx.now.date()
    fixed = render(template, recalled="", followups="", summary="", **fixed_fields)
    recalled, summary, window, followups_text = budget.fit(
        ctx.recalled, ctx.summary, ctx.window, render_followups(ctx.followups),
        # sharing never costs memories, nor do the pages she looked back at (their own two places)
        len(fixed), ctx.user_text, limit=ctx.limit + len(ctx.shared) + len(fixed_fields["pages"]) - len("（没翻）"),
        render_recalled=lambda rs: render_recalled(rs, today),
    )
    system = render(
        template, recalled=render_recalled(recalled, today), followups=followups_text or "（没有）",
        summary=summary or "（这是开头）", **fixed_fields,
    )
    messages: list[dict] = [{"role": "system", "content": system}]
    for t in window:
        messages.append({"role": "user" if t.role == "user" else "assistant", "content": t.text})
    user_text = ctx.user_text
    if ctx.nothing_found:  # said right at his line, where the guess would be made
        user_text = f"{user_text}\n" + owner_words(NOTHING_FOUND)
    if ctx.user_image:  # pictures may only ride in a user message (DeepSeek's rule)
        # With a picture in the message the model sometimes chats in prose before the JSON;
        # a reminder right next to the picture keeps it to the format.
        text = (user_text or owner_words("（他发了一张图）")) + "\n（照“输出格式”，只输出一个 JSON 对象，say 里放你要说的话）"
        messages.append({"role": "user", "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": ctx.user_image}},
        ]})
    else:
        messages.append({"role": "user", "content": user_text})
    return messages


def render_turns(turns: list[Turn]) -> str:
    who = owner_words("他")
    return "\n".join(f"{who if t.role == 'user' else '你'}：{t.text}" for t in turns)


def build_fold_messages(summary: str, turns: list[Turn]) -> list[dict[str, str]]:
    content = render(load_template("fold"), summary=summary or "（无）", turns=render_turns(turns))
    return [{"role": "user", "content": content}]


def render_asked(asked: list[Followup]) -> str:
    """What she asked him in this chat, with the memory each question is about."""
    return "\n".join(f"- {f.text}" + (f"（问的是 #{f.source_memory}）" if f.source_memory else "")
                     for f in asked) or "（没有）"


def render_waiting(waiting: list[Memory]) -> str:
    """Events this chat touched that end in a result, by id, for `outcomes` (memory v3 §B2)."""
    lines = []
    for m in waiting:
        day = told_day(m)
        when = f"（{day.month}月{day.day}日）" if day else ""
        known = f"（已记的结果：{m.outcome}）" if m.outcome else ""
        lines.append(f"- [#{m.id}] {m.text}{when}{known}——" + owner_words("他说结果了吗？"))
    return "\n".join(lines) or "（没有）"


def build_close_messages(summary: str, turns: list[Turn], already: list[str],
                         today: str, known: list[str] | None = None,
                         pacts: list[Memory] | None = None, *, asked: list[Followup] | None = None,
                         waiting: list[Memory] | None = None) -> list[dict[str, str]]:
    """known: what she always carries about him (her profile), so the close can see what is
    still missing and fill in what the chat forgot to write down. today: YYYY-MM-DD; the
    weekday is added here so the notes do not work it out wrong. pacts: the promises still
    open, by id, for `pact_done`. asked: the follow-ups she asked in this chat; waiting: the
    events it touched that end in a result, by id, for `outcomes`."""
    content = render(
        load_template("close_episode"), summary=summary or "（无）", turns=render_turns(turns),
        already="\n".join(f"- {a}" for a in already) or "（无）",
        today=f"{today} 周{WEEKDAYS[date.fromisoformat(today[:10]).weekday()]}",
        known="\n".join(f"- {k}" for k in known or []) or "（还没有）",
        pacts=render_pacts(pacts or []), asked=render_asked(asked or []),
        waiting=render_waiting(waiting or []),
    )
    return [{"role": "user", "content": content}]

"""His plain words for her room (decision 36): "往冰箱放两盒牛奶", "把窗台上的小葱拿走". The model
only translates the line into put / take operations; the room's own rules carry them out (a
full fridge stays full, what is not on the sill cannot be taken)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fish.brain.ask import ask_json
from fish.brain.llm import LLM
from fish.bus import Bus
from fish.cottage import Cottage, RoomNode

PLACES = ("fridge", "rice", "sill", "drawer")


@dataclass(frozen=True)
class Op:
    op: str  # put / take / peek
    where: str  # fridge / rice / sill
    what: str
    meals: int | None = None
    since: str = ""  # visit: "HH:MM" he comes (now when empty or past)
    until: str = ""  # visit: "HH:MM" he leaves


def plan(llm: LLM, text: str, room: str) -> tuple[list[Op], str]:
    """The operations his line asks for, and the model's one line when it found none."""
    data = ask_json(llm, "home_command", text=text.strip(), room=room, temperature=0.2, max_tokens=400) or {}
    ops = []
    for o in data.get("ops") or []:
        if not isinstance(o, dict):
            continue
        op, where, what = str(o.get("op") or ""), str(o.get("where") or ""), str(o.get("what") or "").strip()[:40]
        meals = o.get("meals") if isinstance(o.get("meals"), int) and 0 < o["meals"] <= 30 else None
        if op == "peek" and where == "drawer":
            ops.append(Op(op, where, what or "抽屉"))
        elif op in ("visit", "go_home"):
            ops.append(Op(op, "home", what, None, str(o.get("since") or "")[:5], str(o.get("until") or "")[:5]))
        elif op in ("put", "take") and where in PLACES and where != "drawer" and what:
            ops.append(Op(op, where, what, meals))
    return ops, str(data.get("say") or "").strip()[:80]


def carry_out(cottage: Cottage, ops: list[Op], now: datetime) -> list[str]:
    """Each operation through the room's rules; one line each of what happened."""
    out = []
    for o in ops:
        if o.op in ("visit", "go_home"):
            out.append(RoomNode(Bus(), cottage).visit("arrive" if o.op == "visit" else "leave", now, o.since, o.until, o.what)
                       or "他本来就不在她那")
        elif o.op == "peek":
            letters = cottage.open_drawer(now)
            out.append(f"床头的抽屉里有 {len(letters)} 封信：" if letters else "床头的抽屉里空空的。")
            out += [f"\n【{day}】\n{text}" for day, text in letters]
        elif o.op == "put" and o.where == "sill":
            out.append(cottage.put_on_sill(o.what, now))
        elif o.op == "put":
            out.append(cottage.give("米" if o.where == "rice" else o.what, now, o.meals))
        else:
            line = cottage.take(o.what, now, "" if o.where == "rice" else o.where)
            out.append(line or f"屋里没找到「{o.what}」，没拿")
    return out


def home_command(llm: LLM, cottage: Cottage, text: str, now: datetime) -> list[str]:
    room = cottage.load(now)
    view = "\n".join(f"- {line}" for line in cottage.lines(room).values())
    ops, why = plan(llm, text, view)
    if not ops:
        return [why or "没听懂要放什么、拿什么"]
    return carry_out(cottage, ops, now)

"""Read a book from Wikisource (old books, full text). Her bookmark keeps the place;
she can start one, go on with one, or put one down."""

from __future__ import annotations

from fish.brain.leisure.base import Activity, Choice, Kit, Material
from fish.memory import Pastime
from fish.world import Fetch, FetchError, Item
from fish.world import bot_fetch, find_book, page_url, read_part

KIND = "book"
PART_CHARS = 3000


def _short(book: str, chapter: str) -> str:
    return chapter[len(book) + 1:] if chapter.startswith(book + "/") else chapter


def where(p: Pastime) -> str:
    chapters, i = p.progress.get("chapters") or [p.ref], p.progress.get("i", 0)
    if i >= len(chapters):
        return "读完了"
    at = _short(p.ref, chapters[i])
    return f"读到{at}，读了一部分" if p.progress.get("offset") else f"下一段是{at}"


class BookActivity(Activity):
    key = KIND

    def __init__(self, fetch: Fetch | None = None) -> None:
        self.fetch = fetch or bot_fetch  # Wikimedia asks callers to say who they are

    def offer(self, kit: Kit) -> list[Choice]:
        choices = [Choice(KIND, "开一本书读（维基文库，只有版权过期的老书）", arg_hint="书名")]
        for p in kit.pastimes.active(kit.now, KIND):
            choices.append(Choice(KIND, f"接着读《{p.title}》（{where(p)}）", payload={"id": p.id}))
            choices.append(Choice(KIND, f"不读《{p.title}》了", payload={"id": p.id, "drop": True}))
        return choices

    def do(self, kit: Kit, choice: Choice, picks: list[int], arg: str) -> Material:
        if choice.payload.get("drop"):
            p = kit.pastimes.get(choice.payload["id"])
            kit.pastimes.drop(p.id, kit.now)
            return Material(result=f"不读《{p.title}》了")
        if "id" in choice.payload:
            p = kit.pastimes.get(choice.payload["id"])
        else:
            book = find_book(arg, fetch=self.fetch)
            if book is None:
                return Material(result=f"想读《{arg.strip('《》')}》，维基文库上没找到")
            p = kit.pastimes.start(KIND, book.title, book.title,
                                   {"chapters": list(book.chapters), "i": 0, "offset": 0}, kit.now)
        return self.read_on(kit, p)

    def read_on(self, kit: Kit, p: Pastime) -> Material:
        chapters = p.progress.get("chapters") or [p.ref]
        i, offset = p.progress.get("i", 0), p.progress.get("offset", 0)
        if i >= len(chapters):
            return Material(result=f"《{p.title}》已经读完了")
        try:
            text, total = read_part(chapters[i], offset, fetch=self.fetch, max_chars=PART_CHARS)
        except FetchError:
            return Material(result=f"想接着读《{p.title}》，没打开")
        offset += len(text)
        if offset >= total:
            i, offset = i + 1, 0
        kit.pastimes.advance(p.id, {**p.progress, "i": i, "offset": offset}, kit.now,
                             finished=i >= len(chapters))
        at = _short(p.ref, chapters[p.progress.get("i", 0)])
        item = Item(f"《{p.title}》{at}", page_url(chapters[p.progress.get("i", 0)]), "", "维基文库", "读书")
        return Material([(item, text)], f"读了《{p.title}》{at}的一段")

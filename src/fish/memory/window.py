"""Window: her working memory. The last N unfolded turns of the current episode, verbatim.

When an episode runs past N turns, the oldest FOLD_BATCH turns are handed to the brain to be
folded into the episode's running summary and then marked folded; they stay in `messages`
forever as evidence but leave the prompt.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from fish.memory.longterm import iso

DEFAULT_SIZE = 20
FOLD_BATCH = 10
# Her question he answers in a word ("面试怎么样了？" "过了！", "是下周三吧？" "对"): what she asked
# is his to say as well (said_in). A short answer, not a no, a laugh or a question back.
SHORT_ANSWER = 12
_QUESTION = re.compile(r"[^。！!？?…\n]*(?:[?？]|[吗呢](?=[。！!…~～\s]*$))")
_NOT_AN_ANSWER = re.compile(r"^\s*(?:不|没|错|才不|哪|瞎|乱|你猜|猜|忘|哈|呵|嘿|嗯？|[?？])|[?？吗]\s*$")


def answered(question: str, answer: str) -> str:
    """The questions of her line that his next line answers in a word; "" when none."""
    if len(answer.strip()) > SHORT_ANSWER or _NOT_AN_ANSWER.search(answer):
        return ""
    return "".join(_QUESTION.findall(question))


@dataclass(frozen=True)
class Turn:
    id: int
    role: str  # 'user' | 'fish'
    text: str
    ts: str


def _turns(rows) -> list[Turn]:
    return [Turn(r["id"], r["role"], r["text"], r["ts"]) for r in rows]


class Window:
    def __init__(self, conn: sqlite3.Connection, size: int = DEFAULT_SIZE,
                 fold_batch: int = FOLD_BATCH) -> None:
        self.conn = conn
        self.size = size
        self.fold_batch = fold_batch

    def append(self, role: str, text: str, channel: str, episode_id: int | None = None,
               now: datetime | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO messages (ts, role, text, channel, episode_id, folded)"
            " VALUES (?, ?, ?, ?, ?, 0)",
            (iso(now or datetime.now()), role, text, channel, episode_id),
        )
        self.conn.commit()
        return cur.lastrowid

    def recent(self, episode_id: int | None = None) -> list[Turn]:
        """The last `size` unfolded turns, oldest first; of one episode if given."""
        sql = "SELECT id, role, text, ts FROM messages WHERE folded = 0"
        args: tuple = ()
        if episode_id is not None:
            sql += " AND episode_id = ?"
            args = (episode_id,)
        rows = self.conn.execute(sql + " ORDER BY id DESC LIMIT ?", args + (self.size,)).fetchall()
        return _turns(reversed(rows))

    def unfolded(self, episode_id: int) -> list[Turn]:
        """Every turn of the episode not yet folded into its running summary, oldest first."""
        rows = self.conn.execute(
            "SELECT id, role, text, ts FROM messages WHERE folded = 0 AND episode_id = ? ORDER BY id",
            (episode_id,),
        )
        return _turns(rows)

    def said_in(self, episode_id: int) -> tuple[str, str]:
        """What he said and what she said in the whole episode, folded turns too. Her question
        he answered in a word (`answered`) counts as said by him as well."""
        rows = self.conn.execute("SELECT role, text FROM messages WHERE episode_id = ? ORDER BY id",
                                 (episode_id,)).fetchall()
        his, hers = [], []
        for before, r in zip([None, *rows], rows):
            if r["role"] != "user":
                hers.append(r["text"])
                continue
            his.append(r["text"])
            if before is not None and before["role"] != "user" and (asked := answered(before["text"], r["text"])):
                his.append(asked)
        return "\n".join(his), "\n".join(hers)

    def his_lines(self, episode_id: int) -> list[str]:
        """His lines of the whole episode, folded turns too."""
        return [r["text"] for r in self.conn.execute(
            "SELECT text FROM messages WHERE episode_id = ? AND role = 'user' ORDER BY id", (episode_id,))]

    def to_fold(self, episode_id: int) -> list[Turn]:
        """The oldest turns to summarize away, or [] while the episode still fits."""
        count = self.conn.execute(
            "SELECT COUNT(*) FROM messages WHERE folded = 0 AND episode_id = ?", (episode_id,)
        ).fetchone()[0]
        if count <= self.size:
            return []
        rows = self.conn.execute(
            "SELECT id, role, text, ts FROM messages WHERE folded = 0 AND episode_id = ?"
            " ORDER BY id LIMIT ?",
            (episode_id, self.fold_batch),
        )
        return _turns(rows)

    def mark_folded(self, ids: list[int]) -> None:
        self.conn.executemany("UPDATE messages SET folded = 1 WHERE id = ?", [(i,) for i in ids])
        self.conn.commit()

    def last_ts(self) -> str | None:
        row = self.conn.execute("SELECT ts FROM messages ORDER BY id DESC LIMIT 1").fetchone()
        return row["ts"] if row else None

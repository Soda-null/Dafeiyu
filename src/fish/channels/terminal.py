"""Chat in the terminal. Ctrl-D or an empty line ends it. Pictures cannot travel here:
a sticker she picks is shown as its caption."""

from __future__ import annotations

from fish.channels.base import Incoming, Reply


class TerminalChannel:
    name = "terminal"

    def run(self, reply: Reply) -> None:
        print("（大肥鱼在。直接打字；空行退出。）")
        while True:
            try:
                line = input("你：").strip()
            except EOFError:
                break
            if not line:
                break
            out = reply(Incoming(line))
            print(f"鱼：{out.text}")
            if out.sticker is not None:
                print(f"鱼：（发了个表情包：{out.sticker_caption}）")

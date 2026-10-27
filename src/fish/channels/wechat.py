"""WeChat as the phone line, through Tencent's ClawBot (iLink) channel.

`login` shows a QR code, waits for the user to scan it in WeChat and saves the credentials
to data/wechat.json. `WeChatChannel.run` long-polls for messages, answers only the WeChat
account that scanned the code, and sends each line of her reply as its own bubble.
The brain never sees any of this; it gets plain text through `reply(text)`.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from fish.channels.base import Incoming, Reply
from fish.channels.ilink import (LOGIN_BASE, MSG_USER, TYPING, TYPING_CANCEL, ILinkClient,
                                 ILinkError, SessionExpired, image_item_of, text_of)

STATE_FILE = Path("data/wechat.json")
SEEN_IDS_KEPT = 200
BUBBLE_GAP_SECONDS = 0.6
# People split one thought over several messages ("...麦当劳这种路上的" / "店"). After a
# message arrives she waits a moment for the rest before answering the whole of it.
FRAGMENT_PEEKS, FRAGMENT_PEEK_SECONDS = 2, 2.5
# Community reports (weilink docs): each context_token allows about 10 bot messages, and bot
# messages to someone silent for 24 h are dropped without an error. We stay well under.
TOKEN_QUOTA = 8
TOKENS_KEPT = 20
RETRY_SHORT, RETRY_LONG, RETRY_LONG_AFTER = 2.0, 30.0, 3
QR_REFRESH_LIMIT = 3
RELOGIN_HINT = "微信那边说登录过期了。重新扫码：.venv/bin/python -m fish wechat login"


@dataclass
class WeChatState:
    bot_token: str
    bot_id: str
    user_id: str  # the WeChat account that scanned the code: the only one she answers
    base_url: str = LOGIN_BASE
    get_updates_buf: str = ""
    context_tokens: dict[str, str] = field(default_factory=dict)
    seen_ids: list[str] = field(default_factory=list)
    token_sends: dict[str, int] = field(default_factory=dict)  # messages sent per context token

    @classmethod
    def load(cls, path: Path = STATE_FILE) -> "WeChatState":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})

    def save(self, path: Path = STATE_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")


SHORT_FRAGMENT = 4


def join_fragments(parts: list[str]) -> str:
    """"你" "现在" "几岁" -> "你现在几岁". Short pieces are bits of one sentence and join
    with nothing (Chinese has no spaces); two longer pieces are probably two sentences and
    get a space; Latin letters or digits at the seam get a space so words do not fuse."""
    out = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if out:
            seam_latin = (out[-1].isascii() and out[-1].isalnum()) or (p[0].isascii() and p[0].isalnum())
            both_long = len(out) > SHORT_FRAGMENT and len(p) > SHORT_FRAGMENT
            if seam_latin or both_long:
                out += " "
        out += p
    return out


def show_qr(url: str, out: Callable[[str], None] = print) -> None:
    """Draw the QR code in the terminal when the `qrcode` package is there; always print the URL."""
    try:
        import qrcode  # type: ignore

        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        import io

        buf = io.StringIO()
        qr.print_ascii(out=buf, invert=True)
        out(buf.getvalue())
    except ImportError:
        out("（没装 qrcode 包，画不出二维码；把下面的链接生成二维码再扫）")
    out(f"二维码内容：{url}")


def login(client: ILinkClient, path: Path = STATE_FILE, *, previous: WeChatState | None = None,
          out: Callable[[str], None] = print, ask: Callable[[str], str] = input,
          sleep: Callable[[float], None] = time.sleep, draw: Callable[[str], None] | None = None,
          max_polls: int = 480) -> WeChatState:
    """Scan-to-bind. Blocks until WeChat confirms, the code expires too often, or max_polls."""
    draw = draw or (lambda url: show_qr(url, out))
    tokens = [previous.bot_token] if previous and previous.bot_token else []
    qrcode, url = client.get_qrcode(tokens)
    out("用微信扫这个码，然后在手机上点确认：")
    draw(url)
    verify_code: str | None = None
    base: str | None = None
    refreshes = 0
    for _ in range(max_polls):
        st = client.qrcode_status(qrcode, verify_code, base=base)
        status = st.get("status")
        if status in ("wait", "scaned"):
            if status == "scaned":
                out("扫到了，等你在手机上确认……")
            sleep(1)
        elif status == "need_verifycode":
            verify_code = ask("微信要你输一个验证码：").strip()
        elif status == "scaned_but_redirect":
            host = st.get("redirect_host")
            if host:
                base = f"https://{host}/"
            sleep(1)
        elif status in ("expired", "verify_code_blocked"):
            refreshes += 1
            if refreshes > QR_REFRESH_LIMIT:
                raise ILinkError("二维码过期太多次，下次再试")
            qrcode, url = client.get_qrcode(tokens)
            verify_code = None
            out("二维码过期了，换一个：")
            draw(url)
        elif status == "binded_redirect":
            raise ILinkError("这个微信已经绑在别的程序上了，先在那边解绑")
        elif status == "confirmed":
            state = WeChatState(
                bot_token=str(st.get("bot_token", "")), bot_id=str(st.get("ilink_bot_id", "")),
                user_id=str(st.get("ilink_user_id", "")), base_url=str(st.get("baseurl") or LOGIN_BASE),
            )
            if not state.bot_token or not state.user_id:
                raise ILinkError(f"微信确认了但没给全凭证：{sorted(st)}")
            state.save(path)
            out("绑好了。凭证存在 data/wechat.json（不进 git）。")
            return state
        else:
            sleep(1)
    raise ILinkError("等扫码等太久了，重新来一次")


Tick = Callable[[Callable[[str], bool]], bool]  # brain.tick(send): may call send(text) once


class WeChatChannel:
    name = "wechat"

    def __init__(self, client: ILinkClient, state: WeChatState, path: Path = STATE_FILE, *,
                 sleep: Callable[[float], None] = time.sleep, out: Callable[[str], None] = print,
                 max_polls: int | None = None, tick: Tick | None = None) -> None:
        self.client = client
        self.state = state
        self.path = path
        self.sleep = sleep
        self.out = out
        self.max_polls = max_polls  # tests stop the loop; None runs until Ctrl-C
        self.tick = tick  # between polls: her chance to speak first
        self._typing_tickets: dict[str, str] = {}

    def run(self, reply: Reply) -> None:
        self.out("（大肥鱼在微信上等着。Ctrl-C 退出。）")
        failures = 0
        polls = 0
        while self.max_polls is None or polls < self.max_polls:
            polls += 1
            try:
                msgs, buf = self.client.get_updates(self.state.get_updates_buf)
            except SessionExpired:
                self.out(RELOGIN_HINT)
                return
            except ILinkError as e:
                failures += 1
                self.out(f"微信接口出错（第 {failures} 次）：{e}")
                self.sleep(RETRY_SHORT if failures < RETRY_LONG_AFTER else RETRY_LONG)
                continue
            except KeyboardInterrupt:
                return
            failures = 0
            if buf and buf != self.state.get_updates_buf:
                self.state.get_updates_buf = buf
                self.state.save(self.path)
            if msgs:
                msgs = msgs + self._gather_fragments()
                self.handle_batch(msgs, reply)
            if self.tick is not None and not msgs:
                try:
                    self.tick(self.push)
                except Exception as e:  # noqa: BLE001 - speaking first must never break listening
                    self.out(f"（想先开口时出错：{type(e).__name__}: {e}）")

    def push(self, text: str) -> bool:
        """Send her words unprompted, using the last context token he gave us."""
        user = self.state.user_id
        token = self.state.context_tokens.get(user)
        if not token:
            self.out("（想先开口，但还没有他的对话凭证）")
            return False
        if self._left(token) <= 0:
            self.out("（想先开口，但这张对话凭证的额度用完了）")
            return False
        try:
            self._send_bubbles(user, text, token)
        except ILinkError as e:
            self.out(f"（想先开口，但没发出去：{e}）")
            return False
        self.out(f"她先开口了：{text}")
        return True

    def _left(self, token: str | None) -> int:
        return TOKEN_QUOTA - self.state.token_sends.get(token or "", 0)

    def _spend(self, token: str | None, n: int = 1) -> None:
        key = token or ""
        sends = self.state.token_sends
        sends[key] = sends.get(key, 0) + n
        if len(sends) > TOKENS_KEPT:  # only recent tokens matter
            for old in list(sends)[:-TOKENS_KEPT]:
                del sends[old]
        self.state.save(self.path)

    def _send_bubbles(self, user: str, text: str, token: str | None) -> None:
        bubbles = [line.strip() for line in text.splitlines() if line.strip()] or [text]
        left = self._left(token)
        if left <= 0:
            self.out(f"（这张对话凭证的额度用完了，没发：{text[:30]}）")
            return
        if len(bubbles) > left:  # merge the tail so the reply fits the token's quota
            bubbles = bubbles[:left - 1] + ["\n".join(bubbles[left - 1:])]
        for i, bubble in enumerate(bubbles):
            if i:
                self.sleep(BUBBLE_GAP_SECONDS)
            mid = self.client.send_text(user, bubble, token)
            self._spend(token)
            self.out(f"→ {bubble[:30]}（message_id {mid or '无'}，凭证还剩 {self._left(token)}）")

    def _gather_fragments(self) -> list[dict]:
        """A couple of quick peeks for the rest of what he is typing."""
        more: list[dict] = []
        for _ in range(FRAGMENT_PEEKS):
            try:
                extra, buf = self.client.get_updates(self.state.get_updates_buf, timeout=FRAGMENT_PEEK_SECONDS)
            except ILinkError:
                break
            if buf and buf != self.state.get_updates_buf:
                self.state.get_updates_buf = buf
                self.state.save(self.path)
            if not extra:
                break
            more += extra
        return more

    def _accept(self, msg: dict) -> bool:
        """His, new, and now remembered (id and context token). False for anything else."""
        if msg.get("message_type") != MSG_USER:
            return False
        sender = str(msg.get("from_user_id") or "")
        if sender != self.state.user_id:
            self.out(f"（忽略陌生人 {sender[:8]}… 的消息）")
            return False
        mid = str(msg.get("message_id") or msg.get("client_id") or "")
        if mid and mid in self.state.seen_ids:
            return False
        if mid:
            self.state.seen_ids = (self.state.seen_ids + [mid])[-SEEN_IDS_KEPT:]
        token = msg.get("context_token")
        if token:
            self.state.context_tokens[sender] = str(token)
        self.state.save(self.path)
        return True

    def handle(self, msg: dict, reply: Reply) -> bool:
        return self.handle_batch([msg], reply)

    def handle_batch(self, msgs: list[dict], reply: Reply) -> bool:
        """Everything he sent in one go becomes one turn. True when she got to answer."""
        accepted = [m for m in msgs if self._accept(m)]
        if not accepted:
            return False
        texts: list[str] = []
        image: bytes | None = None
        for msg in accepted:
            item = image_item_of(msg)
            if item is not None and image is None:
                try:
                    image = self.client.download_image(item)
                except ILinkError as e:
                    self.out(f"（他发的图没取到：{e}）")
            text = text_of(msg)
            if text and not (item is not None and text == "[图片]" and image is not None):
                texts.append(text)
        text = join_fragments(texts)
        if not text and image is None:
            return False
        sender = self.state.user_id
        token = self.state.context_tokens.get(sender)
        self._typing(sender, token, TYPING)
        try:
            out = reply(Incoming(text, image))
        finally:
            self._typing(sender, token, TYPING_CANCEL)
        if out.text.strip():
            self._send_bubbles(sender, out.text, token)
        if out.sticker is not None and self._left(token) > 0:
            try:
                mid = self.client.send_image(sender, out.sticker.read_bytes(), token)
                self._spend(token)
                self.out(f"（发了表情包「{out.sticker_caption}」，message_id {mid}）")
            except (ILinkError, OSError) as e:
                self.out(f"（表情包没发出去：{e}）")
        return True

    def _typing(self, user_id: str, token: str | None, status: int) -> None:
        try:
            ticket = self._typing_tickets.get(user_id)
            if not ticket:
                ticket = self.client.typing_ticket(user_id, token)
                if not ticket:
                    return
                self._typing_tickets[user_id] = ticket
            self.client.send_typing(user_id, ticket, status)
        except ILinkError:
            self._typing_tickets.pop(user_id, None)  # best effort only

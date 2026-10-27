"""The WeChat channel against a fake iLink server: request shapes, login, owner-only replies."""

import base64
import json
from pathlib import Path

import pytest

from fish.channels.ilink import (BASE_INFO, LOGIN_BASE, ILinkClient, ILinkError, SessionExpired,
                                 TransportTimeout, text_of)
from fish.channels.wechat import WeChatChannel, WeChatState, login
from fish.messages import Outgoing


class FakeTransport:
    """Records every request; answers by path from `responses` (a list is consumed in order)."""

    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": headers,
                           "body": json.loads(body) if body else None, "timeout": timeout})
        path = url.split("ilink/bot/", 1)[1].split("?")[0]
        r = self.responses[path]
        if isinstance(r, list):
            r = r.pop(0)
        if isinstance(r, Exception):
            raise r
        status, data = r if isinstance(r, tuple) else (200, r)
        return status, json.dumps(data)


def client_with(responses, token="tok"):
    t = FakeTransport(responses)
    return ILinkClient(token, "https://example.test/base", transport=t, random_bytes=lambda n: b"\x00\x00\x01\x00"), t


def test_send_text_request_matches_the_official_plugin():
    c, t = client_with({"sendmessage": {"ret": 0, "message_id": "m1"}})
    assert c.send_text("u@im.wechat", "你好", "ctx-1") == "m1"
    (call,) = t.calls
    assert call["method"] == "POST" and call["url"] == "https://example.test/base/ilink/bot/sendmessage"
    h = call["headers"]
    assert h["Authorization"] == "Bearer tok" and h["AuthorizationType"] == "ilink_bot_token"
    assert h["iLink-App-Id"] == "bot" and h["iLink-App-ClientVersion"] == str((2 << 16) | (4 << 8) | 10)
    assert base64.b64decode(h["X-WECHAT-UIN"]).decode() == "256"
    msg = call["body"]["msg"]
    assert msg["client_id"].startswith("dafeiyu-") and msg["from_user_id"] == ""
    assert (msg["to_user_id"], msg["message_type"], msg["message_state"], msg["context_token"]) == \
        ("u@im.wechat", 2, 2, "ctx-1")
    assert msg["item_list"] == [{"type": 1, "text_item": {"text": "你好"}}]
    assert call["body"]["base_info"] == BASE_INFO


def test_get_updates_cursor_timeout_and_expiry():
    c, t = client_with({"getupdates": [
        {"ret": 0, "msgs": [{"message_type": 1}], "get_updates_buf": "buf2"},
        TransportTimeout("slow"),
        {"ret": 0, "errcode": -14, "errmsg": "stale"},
        (500, {"ret": 0}),
    ]})
    assert c.get_updates("") == ([{"message_type": 1}], "buf2")
    assert t.calls[-1]["body"] == {"get_updates_buf": "", "base_info": BASE_INFO}
    assert c.get_updates("buf2") == ([], "buf2")
    with pytest.raises(SessionExpired):
        c.get_updates("buf2")
    with pytest.raises(ILinkError):
        c.get_updates("buf2")


def test_login_requests_go_to_the_login_host_without_a_token():
    c, t = client_with({"get_bot_qrcode": {"qrcode": "q1", "qrcode_img_content": "https://x/q"},
                        "get_qrcode_status": {"status": "wait"}}, token="")
    assert c.get_qrcode(["old"]) == ("q1", "https://x/q")
    call = t.calls[0]
    assert call["url"] == LOGIN_BASE + "ilink/bot/get_bot_qrcode?bot_type=3"
    assert call["body"] == {"local_token_list": ["old"]} and "Authorization" not in call["headers"]
    c.qrcode_status("q 1", "7")
    assert t.calls[1]["method"] == "GET"
    assert t.calls[1]["url"].endswith("get_qrcode_status?qrcode=q%201&verify_code=7")


def test_text_of_reads_text_voice_and_media_like_the_plugin():
    assert text_of({"item_list": [{"type": 1, "text_item": {"text": "嗨"}}]}) == "嗨"
    assert text_of({"item_list": [{"type": 3, "voice_item": {"text": "转写"}}]}) == "转写"
    assert text_of({"item_list": [{"type": 2, "image_item": {}}]}) == "[图片]"
    assert text_of({"item_list": [{"type": 99}]}) == ""


class FakeClient:
    def __init__(self, updates):
        self.updates = updates  # list of (msgs, buf) or exceptions
        self.sent: list[tuple[str, str, str | None]] = []
        self.typing: list[int] = []

    def get_updates(self, buf, timeout=45.0):
        if timeout < 10:  # a quick peek for fragments: nothing more is coming
            return [], buf
        u = self.updates.pop(0)
        if isinstance(u, Exception):
            raise u
        return u

    def send_text(self, to, text, token):
        self.sent.append((to, text, token))
        return "mid"

    def typing_ticket(self, user_id, token):
        return "ticket"

    def send_typing(self, user_id, ticket, status):
        self.typing.append(status)


def user_msg(mid, text, sender="owner@im.wechat", token="ctx"):
    return {"message_id": mid, "from_user_id": sender, "message_type": 1, "message_state": 2,
            "context_token": token, "item_list": [{"type": 1, "text_item": {"text": text}}]}


def test_channel_answers_only_the_owner_once_per_message(tmp_path: Path):
    path = tmp_path / "wechat.json"
    state = WeChatState(bot_token="tok", bot_id="b", user_id="owner@im.wechat")
    client = FakeClient([
        ([user_msg("1", "在吗"), user_msg("2", "我是谁", sender="stranger@im.wechat"),
          user_msg("1", "在吗"), {"message_type": 2, "from_user_id": "owner@im.wechat"}], "buf1"),
        ([user_msg("3", "再见", token="ctx2")], "buf2"),
    ])
    heard: list[str] = []
    ch = WeChatChannel(client, state, path, sleep=lambda s: None, out=lambda s: None, max_polls=2)
    ch.run(lambda inc: heard.append(inc.text) or Outgoing(f"回：{inc.text}\n第二行"))

    assert heard == ["在吗", "再见"]
    assert client.sent == [("owner@im.wechat", "回：在吗", "ctx"), ("owner@im.wechat", "第二行", "ctx"),
                           ("owner@im.wechat", "回：再见", "ctx2"), ("owner@im.wechat", "第二行", "ctx2")]
    assert client.typing == [1, 2, 1, 2]
    saved = WeChatState.load(path)
    assert saved.get_updates_buf == "buf2" and saved.context_tokens == {"owner@im.wechat": "ctx2"}
    assert saved.seen_ids == ["1", "3"]


def test_channel_backs_off_on_errors_and_stops_on_expiry(tmp_path: Path):
    state = WeChatState(bot_token="tok", bot_id="b", user_id="o")
    client = FakeClient([ILinkError("down"), ILinkError("down"), ILinkError("down"), SessionExpired("-14")])
    naps: list[float] = []
    said: list[str] = []
    ch = WeChatChannel(client, state, tmp_path / "w.json", sleep=naps.append, out=said.append, max_polls=10)
    ch.run(lambda inc: Outgoing(inc.text))
    assert naps == [2.0, 2.0, 30.0]
    assert any("重新扫码" in s for s in said)


class FakeLoginClient:
    def __init__(self, statuses):
        self.statuses = statuses
        self.qr_requests = 0

    def get_qrcode(self, tokens):
        self.qr_requests += 1
        return f"q{self.qr_requests}", f"https://x/q{self.qr_requests}"

    def qrcode_status(self, qrcode, verify_code=None, base=None):
        return self.statuses.pop(0)


def test_login_waits_refreshes_and_saves_credentials(tmp_path: Path):
    client = FakeLoginClient([
        {"status": "wait"}, {"status": "expired"}, {"status": "scaned"},
        {"status": "confirmed", "bot_token": "T", "ilink_bot_id": "B", "ilink_user_id": "U",
         "baseurl": "https://ilinkai.weixin.qq.com"},
    ])
    drawn: list[str] = []
    path = tmp_path / "wechat.json"
    state = login(client, path, out=lambda s: None, sleep=lambda s: None, draw=drawn.append)
    assert (state.bot_token, state.bot_id, state.user_id) == ("T", "B", "U")
    assert state.base_url == "https://ilinkai.weixin.qq.com"
    assert drawn == ["https://x/q1", "https://x/q2"]
    assert WeChatState.load(path).user_id == "U"
    assert "T" not in path.read_text(encoding="utf-8").replace('"bot_token": "T"', "")  # token only in its field


def test_login_gives_up_after_too_many_expired_codes(tmp_path: Path):
    client = FakeLoginClient([{"status": "expired"}] * 4)
    with pytest.raises(ILinkError):
        login(client, tmp_path / "w.json", out=lambda s: None, sleep=lambda s: None, draw=lambda u: None)

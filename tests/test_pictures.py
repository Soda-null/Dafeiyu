"""Pictures both ways (decision 12): WeChat CDN crypto, seeing what he sends, her sticker album."""

import base64
import json
import struct
import zlib
from datetime import datetime
from pathlib import Path

import pytest

from fish.brain import Brain, FakeLLM
from fish.channels import WeChatChannel, WeChatState
from fish.channels.ilink import (ILinkClient, aes_ecb_decrypt, aes_ecb_encrypt, image_key,
                                 padded_size, parse_aes_key)
from fish.config import Settings
from fish.memory import StickerAlbum
from fish.messages import Incoming, Outgoing, sniff_mime
from fish.routines import run_nightly
from fish.storage import connect

T = datetime(2026, 10, 27, 12, 0)
KEY = bytes(range(16))


def png(color=(220, 30, 30), size=8) -> bytes:
    raw = b"".join(b"\x00" + bytes(color) * size for _ in range(size))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_aes_helpers_match_the_plugin():
    data = b"x" * 33
    cipher = aes_ecb_encrypt(data, KEY)
    assert len(cipher) == padded_size(len(data)) == 48
    assert aes_ecb_decrypt(cipher, KEY) == data
    assert parse_aes_key(base64.b64encode(KEY).decode()) == KEY
    assert parse_aes_key(base64.b64encode(KEY.hex().encode()).decode()) == KEY
    assert image_key({"aeskey": KEY.hex()}) == KEY
    assert image_key({"media": {"aes_key": base64.b64encode(KEY).decode()}}) == KEY
    assert image_key({"media": {}}) is None
    assert sniff_mime(png()) == "image/png" and sniff_mime(b"\xff\xd8\xff\xe0") == "image/jpeg"


class FakeCdn:
    """Answers the JSON API and the CDN; records what was uploaded."""

    def __init__(self):
        self.calls = []
        self.blobs = []
        self.stored = aes_ecb_encrypt(png(), KEY)

    def json(self, method, url, headers, body, timeout):
        path = url.split("ilink/bot/", 1)[1].split("?")[0]
        self.calls.append((path, json.loads(body) if body else None))
        if path == "getuploadurl":
            return 200, json.dumps({"ret": 0, "upload_param": "UP%201"})
        if path == "sendmessage":
            return 200, json.dumps({"ret": 0, "message_id": "img1"})
        raise AssertionError(path)

    def blob(self, method, url, headers, body, timeout):
        self.blobs.append((method, url, headers, body))
        if "/download" in url:
            return 200, self.stored, {}
        if "/upload" in url:
            return 200, b"", {"x-encrypted-param": "DL1"}
        raise AssertionError(url)


def test_download_decrypts_his_picture():
    cdn = FakeCdn()
    c = ILinkClient("tok", "https://example.test/", transport=cdn.json, blob_transport=cdn.blob,
                    random_bytes=lambda n: KEY[:n])
    item = {"media": {"encrypt_query_param": "Q/1"}, "aeskey": KEY.hex()}
    assert c.download_image(item) == png()
    assert cdn.blobs[0][1] == "https://novac2c.cdn.weixin.qq.com/c2c/download?encrypted_query_param=Q%2F1"
    item_plain = {"media": {"full_url": "https://cdn.test/x/download"}}
    cdn.stored = png()
    assert c.download_image(item_plain) == png() and cdn.blobs[-1][1] == "https://cdn.test/x/download"


def test_upload_and_send_image_follow_the_plugin():
    cdn = FakeCdn()
    c = ILinkClient("tok", "https://example.test/", transport=cdn.json, blob_transport=cdn.blob,
                    random_bytes=lambda n: KEY[:n])
    assert c.send_image("u@im.wechat", png(), "ctx") == "img1"
    path, body = cdn.calls[0]
    assert path == "getuploadurl"
    assert (body["filekey"], body["aeskey"], body["media_type"], body["no_need_thumb"]) == (KEY.hex(), KEY.hex(), 1, True)
    assert (body["rawsize"], body["filesize"]) == (len(png()), padded_size(len(png())))
    method, url, headers, blob = cdn.blobs[0]
    assert method == "POST" and headers["Content-Type"] == "application/octet-stream"
    assert url == f"https://novac2c.cdn.weixin.qq.com/c2c/upload?encrypted_query_param=UP%25201&filekey={KEY.hex()}"
    assert aes_ecb_decrypt(blob, KEY) == png()
    item = cdn.calls[1][1]["msg"]["item_list"][0]
    assert item["type"] == 2
    assert item["image_item"]["media"] == {"encrypt_query_param": "DL1",
                                           "aes_key": base64.b64encode(KEY.hex().encode()).decode(),
                                           "encrypt_type": 1}
    assert item["image_item"]["mid_size"] == len(blob)


def make_brain(tmp_path: Path, llm):
    conn = connect(tmp_path / "fish.db")
    settings = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db")
    return conn, Brain(conn, settings, llm, persona_text="你是大肥鱼。", stickers_dir=tmp_path / "stickers")


def test_sticker_placeholders_in_her_words_become_the_sticker_field():
    from fish.brain.parse import parse_reply, split_sticker_placeholder

    assert split_sticker_placeholder("喏，赏你一个\n\n[sticker #1]") == ("喏，赏你一个", 1)
    assert split_sticker_placeholder("给你[表情包#3]看") == ("给你看", 3)
    assert split_sticker_placeholder("（表情包 2）") == ("", 2)
    assert split_sticker_placeholder("今天 [图片] 没拍") == ("今天 [图片] 没拍", None)
    r = parse_reply(json.dumps({"say": "喏，赏你一个\n[sticker #1]"}))
    assert r.say == "喏，赏你一个" and r.sticker == 1
    r = parse_reply(json.dumps({"say": "拿去 [#2]", "sticker": 5}))
    assert r.say == "拿去" and r.sticker == 5  # the field wins when both are given


def test_prose_before_json_and_raw_newlines_do_not_leak(tmp_path):
    from fish.brain.parse import extract_json, parse_reply, prose_only

    raw = ('差不多吧，就是比我灵活。\n短手短脚，看着挺好捏。\n'
           '{"say":"这蓝头发是不错……\n但尾巴那条，是鲸鱼吧。","mood":"无聊","image_note":"蓝发鲸鱼娘","sticker":0}')
    r = parse_reply(raw)
    assert r.parsed and r.say.startswith("这蓝头发是不错") and r.image_note == "蓝发鲸鱼娘" and r.sticker is None
    assert extract_json("前面一句 {\"a\": 1} 后面一句 {\"say\": \"x\"}") == {"a": 1}
    bad = '哈哈\n{"say": "这不完整'
    assert parse_reply(bad).say == "哈哈" and not parse_reply(bad).parsed
    assert prose_only('```json\n{"say": "x"}\n```') == ""


def test_she_sees_the_picture_keeps_it_and_sends_it_back_later(tmp_path):
    def respond(messages, json_mode):
        last = messages[-1]["content"]
        if isinstance(last, list):  # the picture turn
            assert last[0]["text"].startswith("看这个\n（照") and last[1]["image_url"]["url"].startswith("data:image/png;base64,")
            assert "别描述图" in messages[0]["content"]  # the picture rule comes with the picture
            return json.dumps({"say": "哈哈哈这鱼比我还胖", "image_note": "一条胖鱼的表情包",
                               "keep_sticker": "嘲笑他胖用的"}, ensure_ascii=False)
        return json.dumps({"say": "给你看个东西", "sticker": 1}, ensure_ascii=False)

    conn, brain = make_brain(tmp_path, FakeLLM(respond))
    out = brain.handle(Incoming("看这个", png()), now=T)
    assert out == Outgoing("哈哈哈这鱼比我还胖")
    assert [t.text for t in brain.window.recent()] == ["[图片：一条胖鱼的表情包] 看这个", "哈哈哈这鱼比我还胖"]
    (s,) = brain.album.all()
    assert s.caption == "嘲笑他胖用的" and s.path.read_bytes() == png() and s.path.suffix == ".png"

    out = brain.handle(Incoming("我又胖了"), now=T)
    assert out.text == "给你看个东西" and out.sticker == s.path and out.sticker_caption == "嘲笑他胖用的"
    assert brain.album.get(1).uses == 1
    assert "[#1] 嘲笑他胖用的" in brain.llm.calls[-1][0][0]["content"]


def test_wechat_channel_fetches_his_picture_and_sends_her_sticker(tmp_path):
    cdn = FakeCdn()
    client = ILinkClient("tok", "https://example.test/", transport=cdn.json, blob_transport=cdn.blob,
                         random_bytes=lambda n: KEY[:n])
    client.get_updates = lambda buf, timeout=45.0: ([] if timeout < 10 else [
        {"message_id": "m1", "from_user_id": "o", "message_type": 1, "context_token": "ctx",
         "item_list": [{"type": 2, "image_item": {"media": {"encrypt_query_param": "Q"}, "aeskey": KEY.hex()}}]}], "b")
    client.typing_ticket = lambda u, t: ""
    sticker = tmp_path / "s.png"
    sticker.write_bytes(png((0, 0, 255)))
    got: list[Incoming] = []
    state = WeChatState(bot_token="tok", bot_id="b", user_id="o")
    ch = WeChatChannel(client, state, tmp_path / "w.json", sleep=lambda s: None, out=lambda s: None, max_polls=1)
    ch.run(lambda inc: got.append(inc) or Outgoing("拿去", sticker, "蓝的"))
    assert got[0].text == "" and got[0].image == png()  # the picture itself replaces the "[图片]" label
    sent = [c for c in cdn.calls if c[0] == "sendmessage"]
    assert sent[0][1]["msg"]["item_list"][0]["text_item"]["text"] == "拿去"
    assert sent[1][1]["msg"]["item_list"][0]["type"] == 2
    assert aes_ecb_decrypt(cdn.blobs[-1][3], KEY) == png((0, 0, 255))


def test_inbox_pictures_become_captioned_stickers_at_night(tmp_path):
    def respond(messages, json_mode):
        content = messages[-1]["content"]
        if isinstance(content, list) and "起个你自己的叫法" in content[0]["text"]:
            return json.dumps({"caption": "装可怜要饭用的", "tags": ["要饭", "可怜"]}, ensure_ascii=False)
        return json.dumps({"diary": "数米粒。", "self_notes": [], "recent": ""})

    conn, brain = make_brain(tmp_path, FakeLLM(respond))
    inbox = tmp_path / "stickers" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "a.png").write_bytes(png())
    (inbox / "notes.txt").write_text("not a picture")
    brain.window.append("user", "你好", "wechat", None, datetime(2026, 10, 26, 12, 0))
    report = run_nightly(conn, datetime(2026, 10, 27, 3, 30), brain=brain)
    assert report["stickers_added"] == 1
    (s,) = StickerAlbum(conn, tmp_path / "stickers").all()
    assert s.caption == "装可怜要饭用的" and s.tags == ("要饭", "可怜") and s.source == "inbox"
    assert not (inbox / "a.png").exists() and (inbox / "notes.txt").exists()


def test_a_sticker_alone_is_an_answer_the_chat_keeps(tmp_path):
    """Decision 34: she may answer with a sticker and no words; the chat records that she sent it,
    so later she does not think she ignored him."""
    llm = FakeLLM([json.dumps({"say": "", "mood": "开心", "sticker": 1}, ensure_ascii=False)])
    conn, brain = make_brain(tmp_path, llm)
    brain.album.add(png((3, 3, 3)), "image/png", "打滚吐泡泡", now=T)
    out = brain.handle(Incoming("哈哈哈你好笨"), now=T)
    assert out.text == "" and out.sticker is not None
    assert [t.text for t in brain.window.recent()] == ["哈哈哈你好笨", "[表情包：打滚吐泡泡]"]

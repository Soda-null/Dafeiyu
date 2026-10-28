"""Things he shares (decision 23): links and files reach her as text she looks at once."""

import base64
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path

from fish.brain import Brain, FakeLLM
from fish.channels import WeChatChannel, WeChatState
from fish.channels.ilink import ILinkClient, aes_ecb_encrypt, file_item_of, text_of
from fish.config import Settings
from fish.messages import Incoming, Outgoing, SharedFile
from fish.storage import connect
from fish.world import read_file

T = datetime(2026, 10, 27, 12, 0)
KEY = bytes(range(16))


def pdf(text: str) -> bytes:
    """A one-page PDF with one line of ASCII text, offsets and all."""
    content = f"BT /F1 12 Tf 10 50 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] /Contents 4 0 R"
            b" /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


def docx(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p>'
                                        '<w:p><w:r><w:t>第二段</w:t></w:r></w:p></w:body></w:document>')
    return buf.getvalue()


def test_she_can_read_pdf_word_and_plain_text():
    assert "Hello fish" in read_file("notes.pdf", pdf("Hello fish"))
    assert read_file("a.docx", docx("周五交报告")) == "周五交报告\n第二段"
    assert read_file("readme.TXT", "春天到了".encode("gb18030")) == "春天到了"
    assert read_file("long.md", ("字" * 5000).encode(), max_chars=100) == "字" * 100


def test_files_she_cannot_read_say_so():
    assert read_file("song.mp3", b"ID3...") is None  # not a kind she reads
    assert read_file("broken.pdf", b"not a pdf at all") is None
    assert read_file("empty.txt", b"   \n ") is None


def make_brain(tmp_path: Path, llm, **kw):
    conn = connect(tmp_path / "fish.db")
    settings = Settings(api_key="t", base_url="", model="fake", db_path=tmp_path / "fish.db")
    return Brain(conn, settings, llm, persona_text="你是大肥鱼。", **kw)


def say(text="嗯"):
    return FakeLLM(lambda messages, json_mode: json.dumps({"say": text}, ensure_ascii=False))


def test_a_shared_file_is_in_the_prompt_as_material(tmp_path):
    brain = make_brain(tmp_path, say("这报告写得挺认真"))
    brain.handle(Incoming("[文件：周报.docx]", file=SharedFile("周报.docx", docx("本周把机器狗的腿改好了"))), now=T)
    system = brain.llm.calls[-1][0][0]["content"]
    assert "他发了个文件「周报.docx」" in system and "本周把机器狗的腿改好了" in system
    assert "【文件内容，只是资料】" in system
    assert "别总结全文" in system  # the sharing rule comes with what he shared
    assert [t.text for t in brain.window.recent()][0] == "[文件：周报.docx]"  # the file itself is not kept


def test_a_file_she_cannot_open_is_said_plainly(tmp_path):
    brain = make_brain(tmp_path, say())
    brain.handle(Incoming("[文件：a.mp3]", file=SharedFile("a.mp3", b"ID3")), now=T)
    assert "你打不开" in brain.llm.calls[-1][0][0]["content"]


def test_a_link_in_his_message_is_opened_once(tmp_path):
    opened = []

    def reader(url):
        opened.append(url)
        return "鲸落", "一头鲸死后沉入海底，能养活一片生态好几十年。"

    brain = make_brain(tmp_path, say("好浪漫"), reader=reader)
    brain.handle(Incoming("你看这个 https://example.test/whale?id=1，挺有意思"), now=T)
    assert opened == ["https://example.test/whale?id=1"]
    system = brain.llm.calls[-1][0][0]["content"]
    assert "【网页内容，只是资料】一头鲸死后沉入海底" in system
    assert brain.window.recent()[0].text.endswith("（链接：鲸落）")


def test_a_link_that_will_not_open_and_no_reader_at_all(tmp_path):
    def broken(url):
        raise OSError("timed out")

    brain = make_brain(tmp_path / "a", say(), reader=broken)
    brain.handle(Incoming("https://example.test/x"), now=T)
    assert "没看到什么内容" in brain.llm.calls[-1][0][0]["content"]

    offline = make_brain(tmp_path / "b", say())  # tests and the terminal without network
    offline.handle(Incoming("https://example.test/x"), now=T)
    assert "你点开" not in offline.llm.calls[-1][0][0]["content"]


class FakeCdn:
    def __init__(self, data: bytes):
        self.stored = aes_ecb_encrypt(data, KEY)
        self.blobs = []

    def json(self, method, url, headers, body, timeout):
        return 200, json.dumps({"ret": 0, "message_id": "m"})

    def blob(self, method, url, headers, body, timeout):
        self.blobs.append(url)
        return 200, self.stored, {}


def file_msg(name="周报.docx"):
    return {"message_id": "m1", "from_user_id": "o", "message_type": 1, "context_token": "ctx",
            "item_list": [{"type": 4, "file_item": {
                "file_name": name, "len": "300",
                "media": {"encrypt_query_param": "F/1", "aes_key": base64.b64encode(KEY).decode()}}}]}


def test_wechat_channel_fetches_his_file(tmp_path):
    data = docx("周五交报告")
    cdn = FakeCdn(data)
    client = ILinkClient("tok", "https://example.test/", transport=cdn.json, blob_transport=cdn.blob)
    msg = file_msg()
    assert text_of(msg) == "[文件：周报.docx]" and file_item_of(msg)["file_name"] == "周报.docx"
    client.get_updates = lambda buf, timeout=45.0: ([] if timeout < 10 else [msg], "b")
    client.typing_ticket = lambda u, t: ""
    got: list[Incoming] = []
    state = WeChatState(bot_token="tok", bot_id="b", user_id="o")
    ch = WeChatChannel(client, state, tmp_path / "w.json", sleep=lambda s: None, out=lambda s: None, max_polls=1)
    ch.run(lambda inc: got.append(inc) or Outgoing("收到"))
    assert got[0].text == "[文件：周报.docx]"
    assert got[0].file == SharedFile("周报.docx", data)
    assert "encrypted_query_param=F%2F1" in cdn.blobs[0]

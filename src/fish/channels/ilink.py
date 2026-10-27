"""Tencent's iLink bot protocol: the HTTP side of WeChat ClawBot.

Mirrored from Tencent's open-source OpenClaw plugin @tencent-weixin/openclaw-weixin 2.4.10
(MIT), the only official client. Only what the fish needs: QR login, long-poll for messages,
send text, typing indicator. Nothing here knows about the brain.

The protocol is published as that plugin's source, not as a documented API, so field names
may change with plugin versions; CHANNEL_VERSION says which version this file mirrors.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Callable

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from fish.messages import data_url, sniff_mime  # noqa: F401 - re-exported for callers

LOGIN_BASE = "https://ilinkai.weixin.qq.com/"
CHANNEL_VERSION = "2.4.10"
CLIENT_VERSION = (2 << 16) | (4 << 8) | 10  # (major << 16) | (minor << 8) | patch
BOT_AGENT = "Dafeiyu/0.0.1 (python)"
BOT_TYPE = "3"
BASE_INFO = {"channel_version": CHANNEL_VERSION, "bot_agent": BOT_AGENT}

STALE_TOKEN = -14  # the server's "scan the QR code again"
LONG_POLL_TIMEOUT = 45.0  # the server holds getupdates for about 35 s

MSG_USER, MSG_BOT = 1, 2
STATE_FINISH = 2
ITEM_TEXT, ITEM_IMAGE, ITEM_VOICE, ITEM_FILE, ITEM_VIDEO = 1, 2, 3, 4, 5
MEDIA_LABELS = {ITEM_IMAGE: "[图片]", ITEM_VOICE: "[语音]", ITEM_FILE: "[文件]", ITEM_VIDEO: "[视频]"}
TYPING, TYPING_CANCEL = 1, 2

# Media: pictures travel through WeChat's CDN, AES-128-ECB (PKCS7) encrypted with a key
# carried in the message. The default host is the one the official plugin's protocol notes
# give; `full_url` in a message takes precedence when present.
CDN_BASE = "https://novac2c.cdn.weixin.qq.com/c2c"
UPLOAD_IMAGE = 1  # UploadMediaType.IMAGE
ENCRYPT_TYPE_AES = 1
MAX_IMAGE_BYTES = 20 * 1024 * 1024


class ILinkError(RuntimeError):
    """A failed request: HTTP error, bad JSON, non-zero ret, or a network problem."""


class SessionExpired(ILinkError):
    """ret / errcode -14: the bot token is stale; the user must scan the QR code again."""


class TransportTimeout(ILinkError):
    """The request timed out. Normal for getupdates when nobody wrote."""


# (method, url, headers, body, timeout) -> (status, text)
Transport = Callable[[str, str, dict[str, str], bytes | None, float], tuple[int, str]]
# (method, url, headers, body, timeout) -> (status, bytes, response headers); for the CDN
BlobTransport = Callable[[str, str, dict[str, str], bytes | None, float],
                         tuple[int, bytes, dict[str, str]]]


def urllib_blob_transport(method: str, url: str, headers: dict[str, str], body: bytes | None,
                          timeout: float) -> tuple[int, bytes, dict[str, str]]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(MAX_IMAGE_BYTES + 1), {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, e.read(), {k.lower(): v for k, v in e.headers.items()}
    except urllib.error.URLError as e:
        raise ILinkError(f"cdn network: {e.reason}") from e
    except (socket.timeout, TimeoutError) as e:
        raise TransportTimeout(str(e)) from e


def aes_ecb_encrypt(plain: bytes, key: bytes) -> bytes:
    padder = padding.PKCS7(128).padder()
    enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return enc.update(padder.update(plain) + padder.finalize()) + enc.finalize()


def aes_ecb_decrypt(cipher: bytes, key: bytes) -> bytes:
    dec = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    unpadder = padding.PKCS7(128).unpadder()
    try:
        return unpadder.update(dec.update(cipher) + dec.finalize()) + unpadder.finalize()
    except ValueError as e:
        raise ILinkError(f"media decrypt failed: {e}") from e


def padded_size(n: int) -> int:
    return ((n + 1 + 15) // 16) * 16


def parse_aes_key(aes_key_b64: str) -> bytes:
    """CDNMedia.aes_key: base64 of the raw 16 bytes, or base64 of a 32-char hex string."""
    raw = base64.b64decode(aes_key_b64)
    if len(raw) == 16:
        return raw
    if len(raw) == 32:
        try:
            return bytes.fromhex(raw.decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            pass
    raise ILinkError("aes_key must decode to 16 raw bytes or a 32-char hex string")


def image_key(image_item: dict) -> bytes | None:
    """The official plugin's rule: image_item.aeskey (hex) wins, else media.aes_key."""
    hexkey = image_item.get("aeskey")
    if hexkey:
        try:
            return bytes.fromhex(str(hexkey))
        except ValueError as e:
            raise ILinkError("image_item.aeskey is not hex") from e
    b64 = (image_item.get("media") or {}).get("aes_key")
    return parse_aes_key(b64) if b64 else None




def urllib_transport(method: str, url: str, headers: dict[str, str], body: bytes | None,
                     timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        if isinstance(e.reason, (socket.timeout, TimeoutError)):
            raise TransportTimeout(str(e.reason)) from e
        raise ILinkError(f"network: {e.reason}") from e
    except (socket.timeout, TimeoutError) as e:
        raise TransportTimeout(str(e)) from e


def _with_slash(url: str) -> str:
    return url if url.endswith("/") else url + "/"


class ILinkClient:
    def __init__(self, token: str = "", base_url: str = LOGIN_BASE, *,
                 transport: Transport = urllib_transport,
                 blob_transport: BlobTransport = urllib_blob_transport,
                 random_bytes: Callable[[int], bytes] = os.urandom,
                 cdn_base: str = CDN_BASE) -> None:
        self.token = token
        self.base_url = _with_slash(base_url)
        self.transport = transport
        self.blob_transport = blob_transport
        self.random_bytes = random_bytes
        self.cdn_base = cdn_base.rstrip("/")

    # --- plumbing --------------------------------------------------------------

    def headers(self) -> dict[str, str]:
        uin = int.from_bytes(self.random_bytes(4), "big")  # new random uint32 per request
        h = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": base64.b64encode(str(uin).encode()).decode(),
            "iLink-App-Id": "bot",
            "iLink-App-ClientVersion": str(CLIENT_VERSION),
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token.strip()}"
        return h

    def _parse(self, path: str, status: int, text: str) -> dict:
        if status >= 400:
            raise ILinkError(f"{path} HTTP {status}: {text[:200]}")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ILinkError(f"{path} returned non-JSON: {text[:200]}") from e
        if not isinstance(data, dict):
            raise ILinkError(f"{path} returned {type(data).__name__}")
        if data.get("ret") == STALE_TOKEN or data.get("errcode") == STALE_TOKEN:
            raise SessionExpired(f"{path}: {data.get('errmsg') or 'token stale'}")
        ret = data.get("ret", 0) or 0
        if ret != 0:
            raise ILinkError(f"{path} ret={ret} errmsg={data.get('errmsg', '')}")
        return data

    def post(self, path: str, body: dict, *, timeout: float = 15.0, base: str | None = None,
             with_base_info: bool = True) -> dict:
        payload = dict(body)
        if with_base_info:
            payload["base_info"] = BASE_INFO
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        status, text = self.transport("POST", _with_slash(base or self.base_url) + path,
                                      self.headers(), raw, timeout)
        return self._parse(path, status, text)

    def get(self, path: str, *, timeout: float = 15.0, base: str | None = None) -> dict:
        headers = {k: v for k, v in self.headers().items() if k != "Content-Type"}
        status, text = self.transport("GET", _with_slash(base or self.base_url) + path,
                                      headers, None, timeout)
        return self._parse(path, status, text)

    # --- login (always against LOGIN_BASE) --------------------------------------

    def get_qrcode(self, local_tokens: list[str] | None = None) -> tuple[str, str]:
        """Returns (qrcode session id, URL to render as a QR image)."""
        data = self.post(f"ilink/bot/get_bot_qrcode?bot_type={BOT_TYPE}",
                         {"local_token_list": list(local_tokens or [])[:10]},
                         base=LOGIN_BASE, with_base_info=False)
        return str(data.get("qrcode", "")), str(data.get("qrcode_img_content", ""))

    def qrcode_status(self, qrcode: str, verify_code: str | None = None,
                      base: str | None = None) -> dict:
        query = "qrcode=" + urllib.parse.quote(qrcode, safe="")
        if verify_code:
            query += "&verify_code=" + urllib.parse.quote(verify_code, safe="")
        return self.get(f"ilink/bot/get_qrcode_status?{query}", timeout=40.0,
                        base=base or LOGIN_BASE)

    # --- messages --------------------------------------------------------------

    def get_updates(self, buf: str, timeout: float = LONG_POLL_TIMEOUT) -> tuple[list[dict], str]:
        """Long-poll. Returns (messages, next cursor); a timeout is (nothing, same cursor).
        A short `timeout` turns it into a peek: cutting the poll early loses nothing, the
        cursor only moves with a successful answer."""
        try:
            data = self.post("ilink/bot/getupdates", {"get_updates_buf": buf}, timeout=timeout)
        except TransportTimeout:
            return [], buf
        msgs = data.get("msgs") or []
        return [m for m in msgs if isinstance(m, dict)], str(data.get("get_updates_buf") or buf)

    def send_text(self, to_user_id: str, text: str, context_token: str | None) -> str:
        msg = {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": f"dafeiyu-{uuid.uuid4().hex}",
            "message_type": MSG_BOT,
            "message_state": STATE_FINISH,
            "item_list": [{"type": ITEM_TEXT, "text_item": {"text": text}}],
        }
        if context_token:
            msg["context_token"] = context_token
        data = self.post("ilink/bot/sendmessage", {"msg": msg})
        return str(data.get("message_id", ""))

    # --- pictures ----------------------------------------------------------------

    def download_image(self, image_item: dict) -> bytes:
        """Fetch and decrypt a picture he sent (image_item of an inbound message)."""
        media = image_item.get("media") or {}
        url = media.get("full_url")
        if not url:
            param = media.get("encrypt_query_param")
            if not param:
                raise ILinkError("image has neither full_url nor encrypt_query_param")
            url = f"{self.cdn_base}/download?encrypted_query_param={urllib.parse.quote(param, safe='')}"
        status, body, _ = self.blob_transport("GET", url, {}, None, 30.0)
        if status != 200:
            raise ILinkError(f"cdn download HTTP {status}")
        if len(body) > MAX_IMAGE_BYTES:
            raise ILinkError("image too large")
        key = image_key(image_item)
        return aes_ecb_decrypt(body, key) if key else body

    def upload_image(self, to_user_id: str, data: bytes) -> dict:
        """Encrypt and upload a picture; returns the image_item for sendmessage."""
        filekey = self.random_bytes(16).hex()
        key = self.random_bytes(16)
        resp = self.post("ilink/bot/getuploadurl", {
            "filekey": filekey, "media_type": UPLOAD_IMAGE, "to_user_id": to_user_id,
            "rawsize": len(data), "rawfilemd5": hashlib.md5(data).hexdigest(),
            "filesize": padded_size(len(data)), "no_need_thumb": True, "aeskey": key.hex(),
        })
        url = (resp.get("upload_full_url") or "").strip()
        if not url:
            param = resp.get("upload_param")
            if not param:
                raise ILinkError("getuploadurl returned no upload URL")
            url = (f"{self.cdn_base}/upload?encrypted_query_param={urllib.parse.quote(param, safe='')}"
                   f"&filekey={urllib.parse.quote(filekey, safe='')}")
        cipher = aes_ecb_encrypt(data, key)
        status, body, headers = self.blob_transport(
            "POST", url, {"Content-Type": "application/octet-stream"}, cipher, 60.0)
        if status != 200:
            raise ILinkError(f"cdn upload HTTP {status}: {headers.get('x-error-message') or body[:100]!r}")
        download_param = headers.get("x-encrypted-param")
        if not download_param:
            raise ILinkError("cdn upload response missing x-encrypted-param")
        return {
            "media": {"encrypt_query_param": download_param,
                      "aes_key": base64.b64encode(key.hex().encode()).decode(),
                      "encrypt_type": ENCRYPT_TYPE_AES},
            "mid_size": len(cipher),
        }

    def send_image(self, to_user_id: str, data: bytes, context_token: str | None) -> str:
        item = {"type": ITEM_IMAGE, "image_item": self.upload_image(to_user_id, data)}
        msg = {
            "from_user_id": "", "to_user_id": to_user_id,
            "client_id": f"dafeiyu-{uuid.uuid4().hex}",
            "message_type": MSG_BOT, "message_state": STATE_FINISH, "item_list": [item],
        }
        if context_token:
            msg["context_token"] = context_token
        return str(self.post("ilink/bot/sendmessage", {"msg": msg}).get("message_id", ""))

    def typing_ticket(self, user_id: str, context_token: str | None) -> str:
        body = {"ilink_user_id": user_id}
        if context_token:
            body["context_token"] = context_token
        return str(self.post("ilink/bot/getconfig", body, timeout=10.0).get("typing_ticket", ""))

    def send_typing(self, user_id: str, ticket: str, status: int) -> None:
        self.post("ilink/bot/sendtyping",
                  {"ilink_user_id": user_id, "typing_ticket": ticket, "status": status}, timeout=10.0)


def image_item_of(msg: dict) -> dict | None:
    for item in msg.get("item_list") or []:
        if isinstance(item, dict) and item.get("type") == ITEM_IMAGE and isinstance(item.get("image_item"), dict):
            return item["image_item"]
    return None


def text_of(msg: dict) -> str:
    """What he said, as the official plugin reads it: text, else a voice transcript,
    else a label like [图片] so she can react to it."""
    for item in msg.get("item_list") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == ITEM_TEXT and (item.get("text_item") or {}).get("text") is not None:
            return str(item["text_item"]["text"])
        if kind == ITEM_VOICE and (item.get("voice_item") or {}).get("text"):
            return str(item["voice_item"]["text"])
        if kind in MEDIA_LABELS:
            return MEDIA_LABELS[kind]
    return ""

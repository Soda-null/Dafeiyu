"""A file he shared -> its readable text, capped (decision 23). PDF, Word, plain text.
Nothing is kept on disk; the brain sees the text once, like a picture."""

from __future__ import annotations

import io
import re
import zipfile

MAX_CHARS = 2500
TEXT_SUFFIXES = (".txt", ".md", ".csv", ".json", ".log", ".py", ".c", ".cpp", ".h", ".java",
                 ".js", ".ts", ".html", ".htm", ".xml", ".yaml", ".yml", ".tex", ".srt")
_TAGS = re.compile(r"<[^>]+>")
_BLANK_LINES = re.compile(r"\n{3,}")


def suffix(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].lower() if dot >= 0 else ""


def _pdf(data: bytes, max_chars: int) -> str:
    from pypdf import PdfReader  # optional: without it a PDF is simply unreadable

    parts: list[str] = []
    size = 0
    for page in PdfReader(io.BytesIO(data)).pages:
        text = page.extract_text() or ""
        parts.append(text)
        size += len(text)
        if size >= max_chars:
            break
    return "\n".join(parts)


def _docx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    xml = xml.replace("</w:p>", "\n").replace("<w:tab/>", " ")
    return _TAGS.sub("", xml)


def _plain(data: bytes) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def read_file(name: str, data: bytes, max_chars: int = MAX_CHARS) -> str | None:
    """The first max_chars of what the file says, or None when she cannot read it
    (an unknown kind, a broken file, a scanned PDF with no text in it)."""
    kind = suffix(name)
    try:
        if kind == ".pdf":
            text = _pdf(data, max_chars)
        elif kind == ".docx":
            text = _docx(data)
        elif kind in TEXT_SUFFIXES:
            text = _plain(data)
        else:
            return None
    except Exception:  # a broken or encrypted file is just one she cannot open
        return None
    text = "\n".join(line.strip() for line in text.splitlines())
    text = _BLANK_LINES.sub("\n\n", text).strip()
    return text[:max_chars] or None

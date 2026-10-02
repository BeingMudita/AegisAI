"""Streaming file parsers for ingestion.

Each parser yields ``(block, bytes_done)`` — a paragraph-sized block of text
and how far into the file it has read — so a large file is processed in
constant memory and the ingestion job can report real progress.

Supported: .txt .md .markdown .log .csv .tsv .jsonl .ndjson .json .html .htm .pdf .docx
"""

from __future__ import annotations

import csv
import json
import re
import zipfile
from collections.abc import Callable, Iterator
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

Block = tuple[str, int]

_READ_LIMIT = 64 * 1024  # max bytes per readline, so a file with no newlines can't blow up memory
_MAX_BLOCK_CHARS = 20_000  # flush a paragraph that never ends
_WHOLE_FILE_LIMIT = 256 * 1024 * 1024  # .json / .html are parsed whole; use .jsonl beyond this
_ROWS_PER_BLOCK = 10


class UnsupportedFile(ValueError):
    pass


def _binary_lines(path: Path) -> Iterator[tuple[str, int]]:
    """Decoded lines with the running byte offset."""
    done = 0
    with path.open("rb") as fh:
        for raw in iter(lambda: fh.readline(_READ_LIMIT), b""):
            done += len(raw)
            yield raw.decode("utf-8", errors="replace"), done


def _text_blocks(path: Path) -> Iterator[Block]:
    para: list[str] = []
    size = 0
    done = 0
    for line, done in _binary_lines(path):
        if line.strip():
            para.append(line.rstrip("\r\n"))
            size += len(line)
            if size < _MAX_BLOCK_CHARS:
                continue
        if para:
            yield "\n".join(para), done
            para, size = [], 0
    if para:
        yield "\n".join(para), done


def _csv_blocks(path: Path, delimiter: str) -> Iterator[Block]:
    progress = {"done": 0}

    def lines() -> Iterator[str]:
        for line, done in _binary_lines(path):
            progress["done"] = done
            yield line

    reader = csv.reader(lines(), delimiter=delimiter)
    header = next(reader, None)
    if header is None:
        return
    rows: list[str] = []
    for row in reader:
        if not any(cell.strip() for cell in row):
            continue
        rows.append(" | ".join(f"{h}: {v}" for h, v in zip(header, row, strict=False) if v.strip()))
        if len(rows) >= _ROWS_PER_BLOCK:
            yield "\n".join(rows), progress["done"]
            rows = []
    if rows:
        yield "\n".join(rows), progress["done"]


def _flatten(obj: Any, prefix: str = "") -> Iterator[str]:
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from _flatten(value, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from _flatten(value, f"{prefix}[{i}]")
    elif obj is not None and str(obj).strip():
        yield f"{prefix}: {obj}" if prefix else str(obj)


def _group(lines: Iterator[str], done: int) -> Iterator[Block]:
    buf: list[str] = []
    size = 0
    for line in lines:
        buf.append(line)
        size += len(line)
        if size >= 2000:
            yield "\n".join(buf), done
            buf, size = [], 0
    if buf:
        yield "\n".join(buf), done


def _jsonl_blocks(path: Path) -> Iterator[Block]:
    for line, done in _binary_lines(path):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            yield line.strip(), done
            continue
        yield from _group(_flatten(record), done)


def _check_whole_file(path: Path) -> int:
    size = path.stat().st_size
    if size > _WHOLE_FILE_LIMIT:
        raise UnsupportedFile(
            f"{path.name} is {size // (1024 * 1024)} MB; files of this type are parsed whole and "
            f"must be under {_WHOLE_FILE_LIMIT // (1024 * 1024)} MB (convert JSON to JSON Lines)."
        )
    return size


def _json_blocks(path: Path) -> Iterator[Block]:
    size = _check_whole_file(path)
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    yield from _group(_flatten(data), size)


class _TextExtractor(HTMLParser):
    _BLOCK_TAGS = {
        "p",
        "div",
        "br",
        "li",
        "tr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "section",
        "article",
    }

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip += 1
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def _html_blocks(path: Path) -> Iterator[Block]:
    size = _check_whole_file(path)
    extractor = _TextExtractor()
    extractor.feed(path.read_text(encoding="utf-8", errors="replace"))
    text = "".join(extractor.parts)
    for para in text.split("\n\n"):
        para = " ".join(para.split())
        if para:
            yield para, size


_B64_TAIL = re.compile(r"[A-Za-z0-9+/]{16,}$")
_B64_HEAD = re.compile(r"^[A-Za-z0-9+/]{4,}={0,2}(?:\s|$)")


def _join_lines(lines: list[str]) -> str:
    out = ""
    for line in lines:
        if out.endswith("-") and line[:1].islower():
            out = out[:-1] + line  # re-join a word hyphenated across lines
        elif _B64_TAIL.search(out) and _B64_HEAD.match(line):
            out += line  # a long encoded token wrapped across lines
        else:
            out = f"{out} {line}" if out else line
    return out


def _pdf_page_paragraphs(page: Any) -> list[str]:
    """Rebuild paragraphs from text positions.

    PDF text extraction has no blank lines between paragraphs, so splitting on
    them would turn a whole page into one chunk (and one injection would
    quarantine the entire page). Instead lines are grouped by their vertical
    position, and a paragraph ends where the gap to the next line is clearly
    larger than the normal line spacing — or where the font size changes
    (headings, tiny hidden text).
    """
    raw: list[list[Any]] = []  # [y, {font_size: visible chars}, text]

    def visit(text: str, cm: Any, tm: Any, font_dict: Any, font_size: float) -> None:
        if not text or text == "\n":
            return
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        size = round(font_size * abs(tm[3] or 1) * abs(cm[3] or 1), 1)
        visible = len(text.strip())
        if raw and abs(raw[-1][0] - y) < 1.0:
            raw[-1][2] += text
            raw[-1][1][size] = raw[-1][1].get(size, 0) + visible
        elif visible:
            raw.append([y, {size: visible}, text])

    page.extract_text(visitor_text=visit)
    # A line's size is the size carrying most of its visible characters, so
    # normal-sized trailing spaces can't mask tiny (hidden) text.
    lines = [[y, max(sizes, key=sizes.get), text] for y, sizes, text in raw if text.strip()]
    if not lines:
        return []

    gaps = [a[0] - b[0] for a, b in zip(lines, lines[1:], strict=False)]
    normal = [g for g, ln in zip(gaps, lines, strict=False) if g >= 0.9 * ln[1]]
    base = min(normal) if normal else 0.0
    sizes = sorted(ln[1] for ln in lines)
    body_size = sizes[len(sizes) // 2]

    paragraphs: list[str] = []
    current: list[str] = [lines[0][2].strip()]
    for prev, line, gap in zip(lines, lines[1:], gaps, strict=False):
        size_change = abs(line[1] - prev[1]) > 0.25 * max(line[1], prev[1])
        if size_change or gap < 0 or (base and gap > 1.3 * base):
            paragraphs.append(_paragraph(current, prev[1], body_size))
            current = []
        current.append(line[2].strip())
    paragraphs.append(_paragraph(current, lines[-1][1], body_size))
    return [p for p in paragraphs if p]


def _paragraph(lines: list[str], size: float, body_size: float) -> str:
    text = _join_lines(lines)
    # Larger, short text is a heading; mark it so the chunker attaches it to
    # the paragraph below instead of making it a chunk of its own.
    if size >= 1.3 * body_size and len(text.split()) <= 15:
        return f"# {text}"
    if text.startswith("#") and len(lines) > 1:
        # Literal '#' text that isn't a heading: keep its first line break so the
        # chunker doesn't mistake the whole paragraph for a markdown heading.
        return f"{lines[0]}\n{_join_lines(lines[1:])}"
    return text


def _pdf_blocks(path: Path) -> Iterator[Block]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is in requirements.txt
        raise UnsupportedFile("PDF support needs the 'pypdf' package.") from exc
    size = path.stat().st_size
    reader = PdfReader(str(path))
    pages = len(reader.pages) or 1
    for i, page in enumerate(reader.pages):
        done = int(size * (i + 1) / pages)
        for para in _pdf_page_paragraphs(page):
            yield para, done


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx_blocks(path: Path) -> Iterator[Block]:
    """Paragraphs of a Word document — including text a reader can't see
    (white or tiny text, text boxes, table cells), because an LLM would."""
    size = path.stat().st_size
    try:
        with zipfile.ZipFile(path) as zf:
            info = zf.getinfo("word/document.xml")
            if info.file_size > _WHOLE_FILE_LIMIT:  # zip-bomb guard
                raise UnsupportedFile(f"{path.name}: document body is too large to parse.")
            xml = zf.read(info)
    except (zipfile.BadZipFile, KeyError) as exc:
        raise UnsupportedFile(f"{path.name} is not a valid .docx file.") from exc
    if b"<!DOCTYPE" in xml[:4096]:  # no DTDs in DOCX; refuse entity-expansion tricks
        raise UnsupportedFile(f"{path.name} contains a DTD, which DOCX files never need.")

    root = ElementTree.fromstring(xml)
    for p in root.iter(f"{_W}p"):
        parts: list[str] = []
        for node in p.iter():
            if node.tag == f"{_W}t":
                parts.append(node.text or "")
            elif node.tag in (f"{_W}br", f"{_W}cr"):
                parts.append("\n")
            elif node.tag == f"{_W}tab":
                parts.append("\t")
        text = "".join(parts).strip()
        if not text:
            continue
        style = p.find(f"{_W}pPr/{_W}pStyle")
        style_name = (style.get(f"{_W}val", "") if style is not None else "").lower()
        if style_name.startswith(("heading", "title")) and "\n" not in text:
            text = f"# {text}"
        yield text, size


_PARSERS: dict[str, Callable[[Path], Iterator[Block]]] = {
    ".txt": _text_blocks,
    ".md": _text_blocks,
    ".markdown": _text_blocks,
    ".log": _text_blocks,
    ".csv": lambda p: _csv_blocks(p, ","),
    ".tsv": lambda p: _csv_blocks(p, "\t"),
    ".jsonl": _jsonl_blocks,
    ".ndjson": _jsonl_blocks,
    ".json": _json_blocks,
    ".html": _html_blocks,
    ".htm": _html_blocks,
    ".pdf": _pdf_blocks,
    ".docx": _docx_blocks,
}

SUPPORTED_EXTENSIONS: tuple[str, ...] = tuple(sorted(_PARSERS))


def is_supported(name: str) -> bool:
    return Path(name).suffix.lower() in _PARSERS


def iter_blocks(path: Path) -> Iterator[Block]:
    """Stream ``path`` as ``(block, bytes_done)`` pairs."""
    parser = _PARSERS.get(path.suffix.lower())
    if parser is None:
        raise UnsupportedFile(
            f"Unsupported file type '{path.suffix}'. Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
    return parser(path)

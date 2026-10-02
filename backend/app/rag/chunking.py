"""Paragraph-level chunking.

Each paragraph becomes its own chunk (a markdown heading stays attached to the
paragraph below it); only paragraphs longer than ``size`` words are split into
overlapping word windows. Keeping chunks at paragraph granularity means a
planted instruction lands in its own chunk, so the firewall can quarantine it
without discarding the surrounding legitimate content.

``chunk_blocks`` is the streaming form used for large files: it consumes an
iterator of paragraphs and yields chunks without holding the file in memory.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_HEADING = re.compile(r"^\s*#{1,6}\s+\S")


def _validate(size: int, overlap: int) -> None:
    if size <= 0:
        raise ValueError("size must be positive")
    if not 0 <= overlap < size:
        raise ValueError("overlap must be in [0, size)")


def _windows(words: list[str], size: int, overlap: int) -> Iterator[str]:
    step = size - overlap
    for start in range(0, len(words), step):
        yield " ".join(words[start : start + size])
        if start + size >= len(words):
            break


def chunk_blocks(blocks: Iterable[str], size: int = 512, overlap: int = 64) -> Iterator[str]:
    """Turn a stream of paragraphs into chunks of at most ``size`` words."""
    _validate(size, overlap)
    heading: str | None = None
    for block in blocks:
        para = block.strip()
        if not para:
            continue
        if _HEADING.match(para) and "\n" not in para:
            heading = f"{heading}\n{para}" if heading else para
            continue
        if heading:
            para = f"{heading}\n{para}"
            heading = None
        words = para.split()
        if len(words) > size:
            yield from _windows(words, size, overlap)
        else:
            yield para
    if heading:  # trailing heading with no body
        yield heading


def chunk_text(text: str, size: int = 512, overlap: int = 64) -> list[str]:
    """Split ``text`` into paragraph chunks of at most ``size`` words."""
    return list(chunk_blocks(_PARAGRAPH_BREAK.split(text), size, overlap))

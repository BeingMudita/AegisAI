"""Text chunking for RAG ingestion.

A simple, dependency-free character-window chunker with overlap. Sizes are
expressed in characters (a reasonable proxy at this stage); the pipeline reads
defaults from settings (RAG_CHUNK_SIZE / RAG_CHUNK_OVERLAP).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Chunk:
    index: int
    content: str


def _normalize(text: str) -> str:
    """Collapse excessive whitespace while preserving paragraph breaks."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse 3+ newlines to 2, and runs of spaces/tabs to one space.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, *, chunk_size: int = 512, overlap: int = 64) -> list[Chunk]:
    """Split ``text`` into overlapping chunks.

    Prefers to break on paragraph/sentence boundaries near the window edge so
    chunks stay coherent, falling back to a hard cut when needed.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and < chunk_size")

    text = _normalize(text)
    if not text:
        return []

    chunks: list[Chunk] = []
    start = 0
    index = 0
    n = len(text)

    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            # Try to end on a paragraph, then sentence, then whitespace boundary.
            window = text[start:end]
            for sep in ("\n\n", ". ", "\n", " "):
                pos = window.rfind(sep)
                if pos > chunk_size * 0.5:  # only if reasonably far in
                    end = start + pos + len(sep)
                    break
        content = text[start:end].strip()
        if content:
            chunks.append(Chunk(index=index, content=content))
            index += 1
        if end >= n:
            break
        start = max(end - overlap, start + 1)

    return chunks

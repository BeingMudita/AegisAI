"""In-memory vector store (cosine similarity over normalized vectors).

The interim index until the pgvector-backed ``embeddings`` table is wired in;
:class:`KnowledgeBase` only uses ``add`` / ``search`` / ``remove_document`` /
``save`` / ``load``, so swapping the backend does not touch the pipeline.

Rows live in a pre-allocated float32 matrix that doubles when full, so bulk
ingestion appends in amortized O(1) instead of copying the index per batch.
Memory is ~1.5 KB per chunk for 384-d vectors plus the chunk text.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import numpy as np

from app.rag.schemas import StoredChunk

_INITIAL_CAPACITY = 1024


class InMemoryVectorStore:
    def __init__(self, dim: int) -> None:
        self.dim = dim
        self._chunks: list[StoredChunk] = []
        self._matrix = np.zeros((_INITIAL_CAPACITY, dim), dtype=np.float32)
        self._lock = threading.Lock()

    def _ensure_capacity(self, needed: int) -> None:
        capacity = self._matrix.shape[0]
        if needed <= capacity:
            return
        while capacity < needed:
            capacity *= 2
        grown = np.zeros((capacity, self.dim), dtype=np.float32)
        grown[: len(self._chunks)] = self._matrix[: len(self._chunks)]
        self._matrix = grown

    def add(self, chunks: list[StoredChunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        if not chunks:
            return
        block = np.asarray(vectors, dtype=np.float32)
        if block.shape[1] != self.dim:
            raise ValueError(f"expected {self.dim}-d vectors, got {block.shape[1]}")
        with self._lock:
            n = len(self._chunks)
            self._ensure_capacity(n + len(chunks))
            self._matrix[n : n + len(chunks)] = block
            self._chunks.extend(chunks)

    def search(self, vector: list[float], k: int) -> list[tuple[StoredChunk, float]]:
        """Return the ``k`` most similar chunks with their cosine similarity."""
        with self._lock:
            n = len(self._chunks)
            if not n:
                return []
            sims = self._matrix[:n] @ np.asarray(vector, dtype=np.float32)
            k = min(k, n)
            top = np.argpartition(-sims, k - 1)[:k]
            order = top[np.argsort(-sims[top])]
            return [(self._chunks[i], float(sims[i])) for i in order]

    def remove_document(self, document_id: str) -> int:
        """Drop every chunk of ``document_id``; returns how many were removed."""
        with self._lock:
            keep = [i for i, c in enumerate(self._chunks) if c.document_id != document_id]
            removed = len(self._chunks) - len(keep)
            if removed:
                rows = self._matrix[keep]
                self._chunks = [self._chunks[i] for i in keep]
                self._matrix = np.zeros(
                    (max(_INITIAL_CAPACITY, len(keep)), self.dim), dtype=np.float32
                )
                self._matrix[: len(keep)] = rows
            return removed

    def chunks_of(self, document_id: str, limit: int = 50) -> list[StoredChunk]:
        with self._lock:
            return [c for c in self._chunks if c.document_id == document_id][:limit]

    def memory_bytes(self) -> int:
        """Approximate memory held by vectors and chunk text."""
        with self._lock:
            n = len(self._chunks)
            return n * self.dim * 4 + sum(len(c.content) for c in self._chunks)

    # ---------------------------------------------------------- persistence
    def save(self, directory: Path) -> None:
        """Write vectors and chunk metadata to ``directory`` (atomically)."""
        directory.mkdir(parents=True, exist_ok=True)
        with self._lock:
            n = len(self._chunks)
            vectors = self._matrix[:n].copy()
            lines = [c.model_dump_json() for c in self._chunks]
        tmp_vec = directory / "vectors.tmp.npy"
        tmp_chunks = directory / "chunks.tmp.jsonl"
        np.save(tmp_vec, vectors)
        tmp_chunks.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        os.replace(tmp_vec, directory / "vectors.npy")
        os.replace(tmp_chunks, directory / "chunks.jsonl")

    def load(self, directory: Path) -> bool:
        """Replace the contents with what ``save`` wrote; False if nothing to load."""
        vec_path, chunk_path = directory / "vectors.npy", directory / "chunks.jsonl"
        if not vec_path.exists() or not chunk_path.exists():
            return False
        vectors = np.load(vec_path)
        with chunk_path.open(encoding="utf-8") as fh:
            chunks = [StoredChunk.model_validate(json.loads(line)) for line in fh if line.strip()]
        if len(chunks) != len(vectors) or (len(chunks) and vectors.shape[1] != self.dim):
            return False
        with self._lock:
            self._chunks = chunks
            self._matrix = np.zeros(
                (max(_INITIAL_CAPACITY, len(chunks)), self.dim), dtype=np.float32
            )
            self._matrix[: len(chunks)] = vectors
        return True

    def __len__(self) -> int:
        return len(self._chunks)

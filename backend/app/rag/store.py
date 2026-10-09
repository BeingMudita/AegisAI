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
from typing import Protocol

import numpy as np

from app.firewall.schemas import FirewallAction
from app.rag.schemas import StoredChunk

_INITIAL_CAPACITY = 1024


class VectorStore(Protocol):
    """What :class:`app.rag.knowledge_base.KnowledgeBase` needs from an index
    (this in-memory one, or :class:`app.persistence.knowledge.PgVectorStore`)."""

    def add(self, chunks: list[StoredChunk], vectors: list[list[float]]) -> None: ...

    def search(self, vector: list[float], k: int) -> list[tuple[StoredChunk, float]]: ...

    def remove_document(self, document_id: str) -> int: ...

    def chunks_of(
        self, document_id: str, limit: int = 50, *, start_index: int = 0
    ) -> list[StoredChunk]: ...

    def memory_bytes(self) -> int: ...

    def entries(
        self,
        *,
        document_ids: set[str] | None,
        query: str | None,
        action: FirewallAction | None,
        offset: int,
        limit: int,
    ) -> tuple[int, list[StoredChunk]]: ...

    def get(self, chunk_id: str) -> tuple[StoredChunk, list[float]] | None: ...

    def replace(self, chunk: StoredChunk, vector: list[float]) -> bool: ...

    def remove(self, chunk_id: str) -> bool: ...

    def find_text(self, text: str, limit: int) -> list[tuple[StoredChunk, list[float]]]: ...

    def save(self, directory: Path) -> None: ...

    def load(self, directory: Path) -> bool: ...

    def __len__(self) -> int: ...


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

    def chunks_of(
        self, document_id: str, limit: int = 50, *, start_index: int = 0
    ) -> list[StoredChunk]:
        with self._lock:
            result = []
            for chunk in self._chunks:
                if chunk.document_id == document_id and chunk.chunk_index >= start_index:
                    result.append(chunk)
                    if len(result) >= limit:
                        break
            return result

    def memory_bytes(self) -> int:
        """Approximate memory held by vectors and chunk text."""
        with self._lock:
            n = len(self._chunks)
            return n * self.dim * 4 + sum(len(c.content) for c in self._chunks)

    # ------------------------------------------------- browsing and editing
    def entries(
        self,
        *,
        document_ids: set[str] | None,
        query: str | None,
        action: FirewallAction | None,
        offset: int,
        limit: int,
    ) -> tuple[int, list[StoredChunk]]:
        """One page of indexed chunks in index order, and how many match in total."""
        needle = query.casefold() if query else None
        with self._lock:
            if document_ids is None and needle is None and action is None:
                return len(self._chunks), self._chunks[offset : offset + limit]
            matches = [
                c
                for c in self._chunks
                if (document_ids is None or c.document_id in document_ids)
                and (action is None or c.firewall_action == action)
                and (needle is None or needle in c.content.casefold())
            ]
        return len(matches), matches[offset : offset + limit]

    def _position(self, chunk_id: str) -> int | None:
        return next((i for i, c in enumerate(self._chunks) if c.id == chunk_id), None)

    def find_text(self, text: str, limit: int) -> list[tuple[StoredChunk, list[float]]]:
        """Chunks containing ``text`` exactly (identifiers such as FIN-000001395), with
        their vectors. A plain scan: only used when a question names an identifier."""
        variants = {text, text.upper(), text.lower()}
        with self._lock:
            found = []
            for i, c in enumerate(self._chunks):
                if any(v in c.content for v in variants):
                    found.append((c, self._matrix[i].tolist()))
                    if len(found) >= limit:
                        break
            return found

    def get(self, chunk_id: str) -> tuple[StoredChunk, list[float]] | None:
        with self._lock:
            i = self._position(chunk_id)
            if i is None:
                return None
            return self._chunks[i], self._matrix[i].tolist()

    def replace(self, chunk: StoredChunk, vector: list[float]) -> bool:
        """Swap one chunk's text and vector in place (same id, same position)."""
        row = np.asarray(vector, dtype=np.float32)
        if row.shape != (self.dim,):
            raise ValueError(f"expected a {self.dim}-d vector, got shape {row.shape}")
        with self._lock:
            i = self._position(chunk.id)
            if i is None:
                return False
            self._chunks[i] = chunk
            self._matrix[i] = row
            return True

    def remove(self, chunk_id: str) -> bool:
        """Drop one chunk; the rows after it shift up in place (no matrix copy)."""
        with self._lock:
            i = self._position(chunk_id)
            if i is None:
                return False
            n = len(self._chunks)
            self._matrix[i : n - 1] = self._matrix[i + 1 : n]
            self._matrix[n - 1] = 0
            del self._chunks[i]
            return True

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

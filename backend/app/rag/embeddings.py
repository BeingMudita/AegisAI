"""Embedding providers.

The default provider uses Sentence-Transformers (the model named by
EMBEDDING_MODEL). When that library/model isn't available — e.g. in CI or a
lightweight dev box — we fall back to a deterministic hashing embedder so the
pipeline still runs end-to-end. The fallback is NOT semantically meaningful;
it exists only to keep the plumbing testable offline.
"""

from __future__ import annotations

import hashlib
import math
from functools import lru_cache
from typing import Protocol

from app.config import get_settings

settings = get_settings()


class EmbeddingProvider(Protocol):
    """Anything that turns text into fixed-length vectors."""

    @property
    def dim(self) -> int: ...

    @property
    def model_name(self) -> str: ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...

    def embed_text(self, text: str) -> list[float]: ...


class SentenceTransformerEmbedder:
    """Real semantic embeddings via sentence-transformers."""

    def __init__(self, model_name: str, expected_dim: int) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self._model_name = model_name
        self._dim = self._model.get_sentence_embedding_dimension()
        if self._dim != expected_dim:
            raise ValueError(
                f"EMBEDDING_DIM={expected_dim} does not match model dim {self._dim}. "
                f"Update EMBEDDING_DIM in your .env to {self._dim}."
            )

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            texts, normalize_embeddings=True, convert_to_numpy=True
        )
        return [v.tolist() for v in vectors]

    def embed_text(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]


class HashEmbedder:
    """Deterministic offline fallback embedder (bag-of-words hashing).

    Not semantic — for plumbing/tests only. Produces L2-normalized vectors of
    the configured dimension so pgvector cosine distance behaves sanely.
    """

    def __init__(self, dim: int) -> None:
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def model_name(self) -> str:
        return f"hash-fallback-{self._dim}"

    def embed_text(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for token in text.lower().split():
            h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            idx = h % self._dim
            sign = 1.0 if (h >> 7) & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(t) for t in texts]


@lru_cache
def get_embedder() -> EmbeddingProvider:
    """Return the configured embedder, falling back to hashing if unavailable."""
    try:
        return SentenceTransformerEmbedder(
            settings.embedding_model, settings.embedding_dim
        )
    except Exception as exc:  # noqa: BLE001 - intentional broad fallback
        import warnings

        warnings.warn(
            f"Falling back to HashEmbedder (sentence-transformers unavailable: {exc}). "
            "Retrieval quality will be poor; install sentence-transformers for real use.",
            RuntimeWarning,
            stacklevel=2,
        )
        return HashEmbedder(settings.embedding_dim)

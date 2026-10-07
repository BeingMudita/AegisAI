"""Text embedders.

``SentenceTransformerEmbedder`` is the real model (``EMBEDDING_MODEL``).
``HashingEmbedder`` is a dependency-free fallback — signed feature hashing of
word unigrams and bigrams — so the RAG pipeline runs (and is testable) on
machines without PyTorch. Both return L2-normalized vectors of
``EMBEDDING_DIM`` dimensions, so cosine similarity is a dot product.
"""

from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache
from typing import Any, Protocol

import structlog

from app.config import get_settings

logger = structlog.get_logger("aegisai.rag")

_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    (  # noqa: SIM905 — a word string is far more readable than a 50-item list
        "a an and are as at be by can do does for from has have how i in is it its me my "
        "of on or our please show tell that the their them there these this to us was we "
        "what when where which who why will with you your"
    ).split()
)


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


class HashingEmbedder:
    """Deterministic bag-of-words embedder using signed feature hashing."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self.name = f"hashing-{dim}"

    @staticmethod
    def _tokens(text: str) -> list[str]:
        words = [w for w in _TOKEN.findall(text.lower()) if w not in _STOPWORDS]
        # crude stemming so "invoices" matches "invoice"
        words = [
            w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words
        ]
        return words + [f"{a}_{b}" for a, b in zip(words, words[1:], strict=False)]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in self._tokens(text):
            h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "little")
            idx = h % self.dim
            sign = 1.0 if (h >> 63) & 1 else -1.0
            vec[idx] += sign * (0.5 if "_" in tok else 1.0)
        return _normalize(vec)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


class SentenceTransformerEmbedder:
    """Wraps a sentence-transformers model (loaded lazily on first use)."""

    def __init__(self, model_name: str, dim: int) -> None:
        self.name = model_name
        self.dim = dim
        self._model = None

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            from app.supply_chain.provenance import verified_huggingface_path

            # Loaded from the snapshot whose files were just checked against their
            # pins (raises ProvenanceError under MODEL_PROVENANCE=enforce).
            self._model = SentenceTransformer(verified_huggingface_path(self.name))
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._load().encode(texts, normalize_embeddings=True)
        return [list(map(float, v)) for v in vectors]


@lru_cache
def get_embedder() -> Embedder:
    """Pick the embedder named by ``EMBEDDING_BACKEND`` (auto falls back to hashing)."""
    settings = get_settings()
    backend = settings.embedding_backend.lower()
    if backend in {"auto", "sentence_transformers"}:
        try:
            import sentence_transformers  # noqa: F401

            return SentenceTransformerEmbedder(settings.embedding_model, settings.embedding_dim)
        except ImportError:
            if backend == "sentence_transformers":
                raise
            logger.warning("sentence_transformers_unavailable", fallback="hashing")
    return HashingEmbedder(settings.embedding_dim)

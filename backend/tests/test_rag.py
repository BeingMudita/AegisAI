"""Offline unit tests for the RAG pipeline components.

These do not require PostgreSQL or Ollama. Full retrieval/generation is covered
by the manual test steps in the README.
"""

from pathlib import Path

import pytest

from app.rag.chunking import chunk_text
from app.rag.embeddings import HashEmbedder
from app.rag.extraction import extract_text
from app.rag.pipeline import build_prompt
from app.rag.schemas import RetrievedChunk

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"


# ------------------------------------------------------------------ chunking
def test_chunking_produces_overlapping_chunks() -> None:
    text = "word " * 500  # ~2500 chars
    chunks = chunk_text(text, chunk_size=200, overlap=40)
    assert len(chunks) > 1
    assert all(len(c.content) <= 220 for c in chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_chunking_empty_text() -> None:
    assert chunk_text("   \n\n  ", chunk_size=100, overlap=10) == []


def test_chunking_rejects_bad_overlap() -> None:
    with pytest.raises(ValueError):
        chunk_text("hello", chunk_size=10, overlap=10)


# ---------------------------------------------------------------- embeddings
def test_hash_embedder_dim_and_determinism() -> None:
    emb = HashEmbedder(dim=384)
    v1 = emb.embed_text("overdue invoice")
    v2 = emb.embed_text("overdue invoice")
    assert len(v1) == 384
    assert v1 == v2  # deterministic
    # normalized to unit length
    assert abs(sum(x * x for x in v1) - 1.0) < 1e-6


# ---------------------------------------------------------------- extraction
def test_extract_markdown() -> None:
    text = extract_text(DATA_DIR / "company_policies" / "payment_terms.md")
    assert "OVERDUE" in text


def test_extract_pdf_invoice() -> None:
    text = extract_text(DATA_DIR / "invoices" / "invoice_42.pdf")
    assert "INV-0042" in text
    assert "OVERDUE" in text


# ------------------------------------------------------------------- prompt
def test_build_prompt_includes_context_and_question() -> None:
    ctx = [
        RetrievedChunk(
            chunk_id="c1",
            document_id="d1",
            document_title="invoice_42",
            source="invoices",
            chunk_index=0,
            content="Invoice INV-0042 is OVERDUE.",
            score=0.91,
        )
    ]
    prompt = build_prompt("Which invoices are overdue?", ctx)
    assert "Which invoices are overdue?" in prompt
    assert "INV-0042" in prompt
    assert "invoice_42" in prompt


def test_build_prompt_no_context() -> None:
    prompt = build_prompt("anything?", [])
    assert "no relevant context" in prompt.lower()

"""Pydantic schemas for the RAG API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=50)


class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str | None = None
    source: str | None = None
    chunk_index: int
    content: str
    score: float  # cosine similarity in [0, 1] (1 == identical direction)


class RetrievalResponse(BaseModel):
    query: str
    top_k: int
    results: list[RetrievedChunk]


class RagAnswer(BaseModel):
    query: str
    answer: str
    model: str
    contexts: list[RetrievedChunk]

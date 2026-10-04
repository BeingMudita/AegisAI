"""RAG knowledge-base tables: document_sources, documents, document_chunks, embeddings."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import get_settings
from app.database.base import Base, TimestampMixin, uuid_pk
from app.database.enums import SourceType, TrustLevel

_EMBEDDING_DIM = get_settings().embedding_dim


class DocumentSource(Base, TimestampMixin):
    """Where documents come from — a file, URL, database, etc. — with a trust level."""

    __tablename__ = "document_sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255), index=True)
    type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, name="source_type"), default=SourceType.MANUAL
    )
    uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    trust_level: Mapped[TrustLevel] = mapped_column(
        Enum(TrustLevel, name="source_trust_level"), default=TrustLevel.UNTRUSTED
    )
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    documents: Mapped[list["Document"]] = relationship(back_populates="source")


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    source: Mapped["DocumentSource | None"] = relationship(back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base, TimestampMixin):
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    document: Mapped["Document"] = relationship(back_populates="chunks")
    embedding: Mapped["Embedding | None"] = relationship(
        back_populates="chunk", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (UniqueConstraint("document_id", "chunk_index", name="uq_chunk_doc_index"),)


class Embedding(Base, TimestampMixin):
    """Vector embedding for a chunk (pgvector)."""

    __tablename__ = "embeddings"

    id: Mapped[uuid.UUID] = uuid_pk()
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), unique=True, index=True
    )
    model: Mapped[str] = mapped_column(String(255))
    vector: Mapped[list[float]] = mapped_column(Vector(_EMBEDDING_DIM))

    chunk: Mapped["DocumentChunk"] = relationship(back_populates="embedding")

    __table_args__ = (
        # Approximate nearest-neighbour index for cosine similarity search.
        Index(
            "ix_embeddings_vector_hnsw",
            "vector",
            postgresql_using="hnsw",
            postgresql_ops={"vector": "vector_cosine_ops"},
        ),
    )


class IngestJobRow(Base):
    """An ingestion job's latest state, so every API worker can report its progress."""

    __tablename__ = "ingest_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    stage: Mapped[str] = mapped_column(String(16), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

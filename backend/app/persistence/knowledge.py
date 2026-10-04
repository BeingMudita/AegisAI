"""The knowledge base on PostgreSQL + pgvector.

``document_sources`` → ``documents`` → ``document_chunks`` → ``embeddings``.
Quarantined chunks are kept as ``document_chunks`` rows flagged in ``meta`` and
never get an embedding, so they can be reviewed but can't be retrieved.
Search orders by cosine distance (HNSW index) and only compares vectors produced
by the current embedding model, so switching models can't mix vector spaces.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.database.enums import TrustLevel
from app.database.models import Document, DocumentChunk, DocumentSource, Embedding
from app.database.sync import get_sync_engine, transaction
from app.firewall.schemas import FirewallAction
from app.rag.knowledge_base import KnowledgeBase
from app.rag.schemas import (
    IngestReport,
    KnowledgeBaseStats,
    QuarantinedChunk,
    SourceSummary,
    StoredChunk,
)

__all__ = ["PgVectorStore", "PostgresKnowledgeBase"]

_SEED_LOCK = 0x5EED_0C0B


def _doc_uuid(document_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(document_id)
    except ValueError:
        return None


class PgVectorStore:
    """Same interface as :class:`app.rag.store.InMemoryVectorStore`."""

    def __init__(self, dim: int, model: str) -> None:
        self.dim = dim
        self.model = model

    def add(self, chunks: list[StoredChunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        with transaction() as db:
            for chunk, vector in zip(chunks, vectors, strict=True):
                row = DocumentChunk(
                    id=uuid.uuid4(),
                    document_id=uuid.UUID(chunk.document_id),
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    token_count=len(chunk.content.split()),
                    meta={
                        "firewall_action": chunk.firewall_action.value,
                        "firewall_score": chunk.firewall_score,
                    },
                )
                db.add(row)
                db.add(Embedding(chunk_id=row.id, model=self.model, vector=vector))

    def search(self, vector: list[float], k: int) -> list[tuple[StoredChunk, float]]:
        distance = Embedding.vector.cosine_distance(vector)
        query = (
            select(
                DocumentChunk,
                Document.title,
                DocumentSource.name,
                DocumentSource.trust_level,
                distance,
            )
            .join(Embedding, Embedding.chunk_id == DocumentChunk.id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(DocumentSource, DocumentSource.id == Document.source_id)
            .where(Embedding.model == self.model)
            .order_by(distance)
            .limit(k)
        )
        with transaction() as db:
            return [
                (
                    StoredChunk(
                        id=f"{chunk.document_id}:{chunk.chunk_index}",
                        document_id=str(chunk.document_id),
                        document_title=title or "",
                        source=source,
                        declared_trust=trust_level,
                        chunk_index=chunk.chunk_index,
                        content=chunk.content,
                        firewall_action=FirewallAction(chunk.meta.get("firewall_action", "ALLOW")),
                        firewall_score=float(chunk.meta.get("firewall_score", 0.0)),
                    ),
                    1.0 - float(dist),
                )
                for chunk, title, source, trust_level, dist in db.execute(query)
            ]

    def remove_document(self, document_id: str) -> int:
        doc = _doc_uuid(document_id)
        if doc is None:
            return 0
        with transaction() as db:
            return db.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == doc)
            ).rowcount

    def chunks_of(self, document_id: str, limit: int = 50) -> list[StoredChunk]:
        doc = _doc_uuid(document_id)
        if doc is None:
            return []
        query = (
            select(DocumentChunk)
            .join(Embedding, Embedding.chunk_id == DocumentChunk.id)
            .where(DocumentChunk.document_id == doc)
            .order_by(DocumentChunk.chunk_index)
            .limit(limit)
        )
        with transaction() as db:
            return [
                StoredChunk(
                    id=f"{c.document_id}:{c.chunk_index}",
                    document_id=str(c.document_id),
                    document_title="",
                    source="",
                    declared_trust=TrustLevel.UNTRUSTED,
                    chunk_index=c.chunk_index,
                    content=c.content,
                    firewall_action=FirewallAction(c.meta.get("firewall_action", "ALLOW")),
                    firewall_score=float(c.meta.get("firewall_score", 0.0)),
                )
                for c in db.scalars(query)
            ]

    def memory_bytes(self) -> int:
        """On-disk size of the chunk and embedding tables (indexes included)."""
        with transaction() as db:
            return int(
                db.scalar(
                    text(
                        "SELECT pg_total_relation_size('embeddings') + "
                        "pg_total_relation_size('document_chunks')"
                    )
                )
                or 0
            )

    def __len__(self) -> int:
        with transaction() as db:
            return (
                db.scalar(
                    select(func.count()).select_from(Embedding).where(Embedding.model == self.model)
                )
                or 0
            )


class PostgresKnowledgeBase(KnowledgeBase):
    def __init__(self, **kwargs: Any) -> None:
        embedder = kwargs["embedder"]
        super().__init__(**kwargs, store=PgVectorStore(embedder.dim, embedder.name))

    # ------------------------------------------------------- storage hooks
    @staticmethod
    def _source_id(db: Session, name: str, level: TrustLevel) -> uuid.UUID:
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"src:{name.lower()}"},
        )
        source = db.scalars(
            select(DocumentSource).where(func.lower(DocumentSource.name) == name.lower())
        ).first()
        if source is None:
            source = DocumentSource(id=uuid.uuid4(), name=name, trust_level=level)
            db.add(source)
        else:
            source.trust_level = level  # the latest declaration wins, as in memory mode
        return source.id

    def _begin_document(self, report: IngestReport) -> None:
        with transaction() as db:
            db.add(
                Document(
                    id=uuid.UUID(report.document_id),
                    source_id=self._source_id(db, report.source, report.trust_level),
                    title=report.title,
                    meta={**report.model_dump(mode="json"), "complete": False},
                )
            )

    def _record_quarantine(
        self, report: IngestReport, index: int, text: str, chunk: QuarantinedChunk
    ) -> None:
        with transaction() as db:
            db.add(
                DocumentChunk(
                    document_id=uuid.UUID(report.document_id),
                    chunk_index=index,
                    content=text,
                    token_count=len(text.split()),
                    meta={
                        "quarantined": True,
                        "firewall_action": FirewallAction.BLOCK.value,
                        "firewall_score": chunk.score,
                        "categories": chunk.categories,
                    },
                )
            )

    def _complete_document(self, report: IngestReport) -> None:
        with transaction() as db:
            doc = db.get(Document, uuid.UUID(report.document_id))
            if doc is not None:
                doc.meta = {**report.model_dump(mode="json"), "complete": True}

    def _rollback(self, document_id: str) -> None:
        doc = _doc_uuid(document_id)
        if doc is None:
            return
        with transaction() as db:
            db.execute(delete(Document).where(Document.id == doc))

    # ------------------------------------------------------------ documents
    def documents(self) -> list[IngestReport]:
        with transaction() as db:
            rows = db.scalars(
                select(Document)
                .where(Document.meta["complete"].astext == "true")
                .order_by(Document.created_at.desc())
            ).all()
            return [IngestReport.model_validate(d.meta) for d in rows]

    def remove_document(self, document_id: str) -> bool:
        doc = _doc_uuid(document_id)
        if doc is None:
            return False
        with transaction() as db:
            return db.execute(delete(Document).where(Document.id == doc)).rowcount > 0

    def quarantine(self) -> list[QuarantinedChunk]:
        query = (
            select(DocumentChunk, Document.title, DocumentSource.name)
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(DocumentSource, DocumentSource.id == Document.source_id)
            .where(DocumentChunk.meta["quarantined"].astext == "true")
            .order_by(DocumentChunk.created_at)
        )
        with transaction() as db:
            return [
                QuarantinedChunk(
                    chunk_id=f"{c.document_id}:{c.chunk_index}",
                    document_title=title or "",
                    source=source,
                    score=float(c.meta.get("firewall_score", 0.0)),
                    categories=list(c.meta.get("categories", [])),
                    excerpt=c.content[:200],
                )
                for c, title, source in db.execute(query)
            ]

    def stats(self) -> KnowledgeBaseStats:
        docs = self.documents()
        with transaction() as db:
            levels = {s.name: s.trust_level for s in db.scalars(select(DocumentSource))}
            quarantined = (
                db.scalar(
                    select(func.count())
                    .select_from(DocumentChunk)
                    .where(DocumentChunk.meta["quarantined"].astext == "true")
                )
                or 0
            )
        per_source: dict[str, list[IngestReport]] = {}
        for d in docs:
            per_source.setdefault(d.source, []).append(d)
        summaries = []
        for source, items in sorted(per_source.items()):
            level = levels.get(source, items[0].trust_level)
            summaries.append(
                SourceSummary(
                    source=source,
                    trust_level=level,
                    trust_score=self.trust.register_source(source, level),
                    documents=len(items),
                    chunks_indexed=sum(d.chunks_indexed for d in items),
                )
            )
        indexed = len(self.store)
        return KnowledgeBaseStats(
            index_ready=indexed > 0,
            embedder=self.embedder.name,
            documents=len(docs),
            bytes_ingested=sum(d.size_bytes for d in docs),
            chunks_screened=sum(d.chunks_total for d in docs),
            chunks_indexed=indexed,
            chunks_flagged=sum(d.chunks_flagged for d in docs),
            chunks_quarantined=quarantined,
            sources=[s.source for s in summaries],
            source_summaries=summaries,
            memory_bytes=self.store.memory_bytes(),
            persisted=True,
        )

    # ---------------------------------------------------------- persistence
    def save(self) -> None:
        """Every write is already durable."""

    def load(self) -> bool:
        """True when the database already holds documents (so nothing is re-seeded)."""
        with transaction() as db:
            return db.scalar(select(func.count()).select_from(Document)) > 0

    def seed_if_empty(self) -> None:
        """Seed the demo corpus once, even when several workers start together."""
        from app.rag.knowledge_base import seed_knowledge_base

        with get_sync_engine().connect() as conn:  # session-level lock for the whole seeding
            conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _SEED_LOCK})
            try:
                if not self.load():
                    seed_knowledge_base(self)
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _SEED_LOCK})
                conn.commit()

    def truncate_for_tests(self) -> None:
        with transaction() as db:
            db.execute(delete(Document))
            db.execute(delete(DocumentSource))

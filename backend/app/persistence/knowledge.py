"""The knowledge base on PostgreSQL + pgvector.

``document_sources`` → ``documents`` → ``document_chunks`` → ``embeddings``.
Quarantined chunks are kept as ``document_chunks`` rows flagged in ``meta`` and
never get an embedding, so they can be reviewed but can't be retrieved.
Search orders by cosine distance (HNSW index) and only compares vectors produced
by the current embedding model, so switching models can't mix vector spaces.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select, text
from sqlalchemy.orm import Session

from app.database.enums import TrustLevel
from app.database.models import Document, DocumentChunk, DocumentSource, Embedding
from app.database.sync import get_sync_engine, transaction
from app.firewall.schemas import FirewallAction
from app.rag.knowledge_base import KnowledgeBase
from app.rag.schemas import (
    ArchiveLocation,
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


def _chunk_key(chunk_id: str) -> tuple[uuid.UUID, int] | None:
    """``"<document uuid>:<chunk index>"`` → its parts (None if malformed)."""
    document_id, _, index = chunk_id.rpartition(":")
    identity = _doc_uuid(document_id)
    if identity is None or not index.isdigit():
        return None
    return identity, int(index)


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
            result = db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc))
            return cast(CursorResult[Any], result).rowcount

    def chunks_of(
        self, document_id: str, limit: int = 50, *, start_index: int = 0
    ) -> list[StoredChunk]:
        doc = _doc_uuid(document_id)
        if doc is None:
            return []
        query = (
            select(DocumentChunk)
            .join(Embedding, Embedding.chunk_id == DocumentChunk.id)
            .where(DocumentChunk.document_id == doc, DocumentChunk.chunk_index >= start_index)
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

    # ------------------------------------------------- browsing and editing
    @staticmethod
    def _stored(
        c: DocumentChunk, title: str | None, source: str | None, level: TrustLevel | None
    ) -> StoredChunk:
        return StoredChunk(
            id=f"{c.document_id}:{c.chunk_index}",
            document_id=str(c.document_id),
            document_title=title or "",
            source=source or "",
            declared_trust=level or TrustLevel.UNTRUSTED,
            chunk_index=c.chunk_index,
            content=c.content,
            firewall_action=FirewallAction(c.meta.get("firewall_action", "ALLOW")),
            firewall_score=float(c.meta.get("firewall_score", 0.0)),
        )

    def _indexed(self, *conditions: Any) -> Any:
        """Indexed chunks (those with an embedding of this model) with their document and source."""
        return (
            select(DocumentChunk, Document.title, DocumentSource.name, DocumentSource.trust_level)
            .join(Embedding, Embedding.chunk_id == DocumentChunk.id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .outerjoin(DocumentSource, DocumentSource.id == Document.source_id)
            .where(Embedding.model == self.model, *conditions)
        )

    def entries(
        self,
        *,
        document_ids: set[str] | None,
        query: str | None,
        action: FirewallAction | None,
        offset: int,
        limit: int,
    ) -> tuple[int, list[StoredChunk]]:
        conditions: list[Any] = []
        if document_ids is not None:
            ids = [u for d in document_ids if (u := _doc_uuid(d)) is not None]
            if not ids:
                return 0, []
            conditions.append(DocumentChunk.document_id.in_(ids))
        if query:
            conditions.append(DocumentChunk.content.icontains(query, autoescape=True))
        if action is not None:
            conditions.append(DocumentChunk.meta["firewall_action"].astext == action.value)
        rows = self._indexed(*conditions)
        page = rows.order_by(
            Document.created_at, DocumentChunk.document_id, DocumentChunk.chunk_index
        )
        with transaction() as db:
            total = db.scalar(select(func.count()).select_from(rows.subquery())) or 0
            return total, [
                self._stored(*row) for row in db.execute(page.offset(offset).limit(limit))
            ]

    def get(self, chunk_id: str) -> tuple[StoredChunk, list[float]] | None:
        key = _chunk_key(chunk_id)
        if key is None:
            return None
        query = self._indexed(
            DocumentChunk.document_id == key[0], DocumentChunk.chunk_index == key[1]
        ).add_columns(Embedding.vector)
        with transaction() as db:
            row = db.execute(query).first()
            if row is None:
                return None
            chunk, title, source, level, vector = row
            return self._stored(chunk, title, source, level), [float(x) for x in vector]

    def replace(self, chunk: StoredChunk, vector: list[float]) -> bool:
        key = _chunk_key(chunk.id)
        if key is None:
            return False
        with transaction() as db:
            row = db.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == key[0], DocumentChunk.chunk_index == key[1])
                .with_for_update()
            ).first()
            if row is None or row.meta.get("quarantined"):
                return False
            row.content = chunk.content
            row.token_count = len(chunk.content.split())
            row.meta = {
                **row.meta,
                "firewall_action": chunk.firewall_action.value,
                "firewall_score": chunk.firewall_score,
            }
            embedding = db.scalars(select(Embedding).where(Embedding.chunk_id == row.id)).first()
            if embedding is None:
                db.add(Embedding(chunk_id=row.id, model=self.model, vector=vector))
            else:
                embedding.model, embedding.vector = self.model, vector
            return True

    def remove(self, chunk_id: str) -> bool:
        key = _chunk_key(chunk_id)
        if key is None:
            return False
        with transaction() as db:
            result = db.execute(
                delete(DocumentChunk).where(  # the embedding goes with it (ON DELETE CASCADE)
                    DocumentChunk.document_id == key[0],
                    DocumentChunk.chunk_index == key[1],
                    DocumentChunk.id.in_(select(Embedding.chunk_id)),
                )
            )
            return cast(CursorResult[Any], result).rowcount > 0

    def find_text(self, text: str, limit: int) -> list[tuple[StoredChunk, list[float]]]:
        query = self._indexed(DocumentChunk.content.icontains(text, autoescape=True))
        with transaction() as db:
            rows = db.execute(query.add_columns(Embedding.vector).limit(limit)).all()
            return [
                (self._stored(c, title, source, level), [float(x) for x in vector])
                for c, title, source, level, vector in rows
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

    def save(self, directory: Path) -> None:
        """Nothing to write: every change is already in the database."""

    def load(self, directory: Path) -> bool:
        """Nothing to read: the index lives in the database."""
        return len(self) > 0

    def __len__(self) -> int:
        with transaction() as db:
            return (
                db.scalar(
                    select(func.count()).select_from(Embedding).where(Embedding.model == self.model)
                )
                or 0
            )


class PostgresKnowledgeBase(KnowledgeBase):
    backend_name = "pgvector"

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
                    content_hash=report.content_hash,
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

    def find_by_hash(
        self,
        content_hash: str,
        *,
        filename: str | None = None,
        section: str | None = None,
        folder: str | None = None,
    ) -> IngestReport | None:
        query = select(Document).where(
            Document.content_hash == content_hash,
            Document.meta["complete"].astext == "true",
        )
        for key, value in (("filename", filename), ("section", section), ("folder", folder)):
            if value is not None:
                query = query.where(Document.meta[key].astext == value)
        with transaction() as db:
            row = db.scalars(query.limit(1)).first()
            return IngestReport.model_validate(row.meta) if row else None

    def document(self, document_id: str) -> IngestReport | None:
        identity = _doc_uuid(document_id)
        if identity is None:
            return None
        with transaction() as db:
            row = db.get(Document, identity)
            return (
                IngestReport.model_validate(row.meta) if row and row.meta.get("complete") else None
            )

    def move_document(self, document_id: str, location: ArchiveLocation) -> IngestReport | None:
        identity = _doc_uuid(document_id)
        if identity is None:
            return None
        with transaction() as db:
            row = db.get(Document, identity, with_for_update=True)
            if row is None or not row.meta.get("complete"):
                return None
            row.meta = {**row.meta, **location.model_dump()}
            return IngestReport.model_validate(row.meta)

    def mark_reviewed(
        self, document_ids: Iterable[str], *, reviewed_by: str, note: str | None = None
    ) -> list[str]:
        ids = {u: d for d in dict.fromkeys(document_ids) if (u := _doc_uuid(d)) is not None}
        if not ids:
            return []
        stamp = {
            "reviewed_by": reviewed_by,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "review_note": note,
        }
        with transaction() as db:
            rows = db.scalars(
                select(Document).where(Document.id.in_(ids)).with_for_update()
            ).all()
            found = []
            for row in rows:
                if row.meta.get("complete"):
                    row.meta = {**row.meta, **stamp}
                    found.append(ids[row.id])
        return [d for d in ids.values() if d in set(found)]

    def _adjust_counts(self, document_id: str, *, indexed: int = 0, flagged: int = 0) -> None:
        identity = _doc_uuid(document_id)
        if identity is None:
            return
        with transaction() as db:
            row = db.get(Document, identity, with_for_update=True)
            if row is None:
                return
            row.meta = {
                **row.meta,
                "chunks_indexed": max(0, int(row.meta.get("chunks_indexed", 0)) + indexed),
                "chunks_flagged": max(0, int(row.meta.get("chunks_flagged", 0)) + flagged),
            }

    def archive_entries(self, document_id: str, offset: int, limit: int) -> list[dict[str, Any]]:
        identity = _doc_uuid(document_id)
        if identity is None:
            return []
        query = (
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == identity,
                DocumentChunk.chunk_index >= offset,
                DocumentChunk.chunk_index < offset + limit,
            )
            .order_by(DocumentChunk.chunk_index)
            .limit(limit)
        )
        with transaction() as db:
            return [
                {
                    "chunk_index": c.chunk_index,
                    "content": c.content,
                    "firewall_action": c.meta.get("firewall_action", "ALLOW"),
                    "firewall_score": float(c.meta.get("firewall_score", 0.0)),
                    "indexed": not c.meta.get("quarantined", False),
                    "categories": list(c.meta.get("categories", [])),
                    "characters": len(c.content),
                    "size_bytes": len(c.content.encode("utf-8")),
                    "word_count": len(c.content.split()),
                    "excerpt_only": False,
                }
                for c in db.scalars(query)
            ]

    def remove_document(self, document_id: str) -> bool:
        doc = _doc_uuid(document_id)
        if doc is None:
            return False
        with transaction() as db:
            result = db.execute(delete(Document).where(Document.id == doc))
            return cast(CursorResult[Any], result).rowcount > 0

    def remove_documents(self, document_ids: Iterable[str]) -> list[str]:
        """Remove several documents in one transaction; returns the ids removed."""
        wanted = {doc: d for d in dict.fromkeys(document_ids) if (doc := _doc_uuid(d)) is not None}
        if not wanted:
            return []
        query = delete(Document).where(Document.id.in_(wanted)).returning(Document.id)
        with transaction() as db:
            gone = set(db.scalars(query))
        return [d for doc, d in wanted.items() if doc in gone]

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
            source_count=len(summaries),
            memory_bytes=self.store.memory_bytes(),
            persisted=True,
        )

    # ---------------------------------------------------------- persistence
    def save(self, *, meta_only: bool = False) -> None:
        """Every write is already durable."""

    def load(self) -> bool:
        """True when the database already holds documents (so nothing is re-seeded)."""
        with transaction() as db:
            return (db.scalar(select(func.count()).select_from(Document)) or 0) > 0

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

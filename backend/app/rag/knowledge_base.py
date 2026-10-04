"""The guarded knowledge base — ingestion and retrieval with zero-trust checks.

Ingestion (streaming, in batches of ``INGEST_BATCH_SIZE`` chunks):
    parse → chunk → firewall scan (RETRIEVED channel)
      BLOCK: quarantine the chunk and penalize the source's trust
      FLAG:  redact the matched spans, small trust penalty
    → embed → index → (persist to data/index/)
Retrieval:
    embed query → nearest neighbours → drop weak matches, UNTRUSTED sources and
    sources whose trust has fallen too low → re-scan each chunk (defense in
    depth) → top-k context.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from collections.abc import Callable, Iterable, Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog
import yaml

from app.config import get_settings
from app.database.enums import SourceType, SubjectType, TrustLevel
from app.firewall.scanner import PromptFirewall, get_firewall
from app.firewall.schemas import ContentChannel, FirewallAction
from app.policies.config import RagPolicy, get_global_config
from app.rag.chunking import chunk_blocks
from app.rag.embeddings import Embedder, get_embedder
from app.rag.schemas import (
    DocumentChunkView,
    DroppedChunk,
    IngestReport,
    IngestRequest,
    IngestStage,
    KnowledgeBaseStats,
    QuarantinedChunk,
    RetrievalResult,
    RetrievedChunk,
    SourceSummary,
    StoredChunk,
)
from app.rag.store import InMemoryVectorStore, VectorStore
from app.telemetry.store import get_audit_log
from app.trust.engine import TrustEngine, get_trust_engine
from app.trust.scoring import TrustSignal

SEED_DIR = Path(__file__).parent / "seed"
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
logger = structlog.get_logger("aegisai.rag")

# progress(stage, bytes_done, running_report)
ProgressFn = Callable[[IngestStage, int, IngestReport], None]


class IngestCancelled(Exception):
    pass


class DuplicateDocument(Exception):
    """The content is already in the knowledge base."""

    def __init__(self, existing: IngestReport) -> None:
        super().__init__(
            f"Already in the knowledge base as '{existing.title}' "
            f"(document {existing.document_id}); delete it first to re-index."
        )
        self.existing = existing


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


class KnowledgeBase:
    def __init__(
        self,
        *,
        embedder: Embedder,
        firewall: PromptFirewall,
        trust: TrustEngine,
        policy: RagPolicy,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        top_k: int = 5,
        batch_size: int = 256,
        persist_dir: Path | None = None,
        store: VectorStore | None = None,
    ) -> None:
        self.embedder = embedder
        self.firewall = firewall
        self.trust = trust
        self.policy = policy
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.top_k = top_k
        self.batch_size = batch_size
        self.persist_dir = persist_dir
        self.store: VectorStore = store if store is not None else InMemoryVectorStore(embedder.dim)
        self._documents: dict[str, IngestReport] = {}
        self._source_levels: dict[str, TrustLevel] = {}
        self._quarantine: list[QuarantinedChunk] = []
        self._lock = threading.Lock()
        self._save_lock = threading.Lock()

    # ------------------------------------------------------------ ingestion
    def ingest(self, req: IngestRequest) -> IngestReport:
        """Chunk, screen, embed and index one in-memory document.

        Raises :class:`DuplicateDocument` if the same text is already indexed.
        """
        content_hash = text_hash(req.content)
        if existing := self.find_by_hash(content_hash):
            raise DuplicateDocument(existing)
        report = self.ingest_stream(
            ((para, 0) for para in _PARAGRAPH_BREAK.split(req.content)),
            title=req.title,
            source=req.source,
            trust_level=req.trust_level,
            source_type=req.source_type,
            size_bytes=len(req.content.encode("utf-8")),
            content_hash=content_hash,
        )
        self.save()
        return report

    def ingest_stream(
        self,
        blocks: Iterable[tuple[str, int]],
        *,
        title: str,
        source: str,
        trust_level: TrustLevel,
        source_type: SourceType = SourceType.MANUAL,
        filename: str | None = None,
        size_bytes: int = 0,
        content_hash: str | None = None,
        progress: ProgressFn | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> IngestReport:
        """Ingest a stream of ``(paragraph, bytes_done)`` blocks in batches.

        On cancellation or error the partially indexed document is rolled back.
        """
        document_id = str(uuid.uuid4())
        with self._lock:
            self._source_levels[source.lower()] = trust_level
        self.trust.register_source(source, trust_level)
        report = IngestReport(
            document_id=document_id,
            title=title,
            source=source,
            chunks_total=0,
            chunks_indexed=0,
            chunks_flagged=0,
            chunks_quarantined=0,
            trust_level=trust_level,
            source_type=source_type,
            filename=filename,
            size_bytes=size_bytes,
            content_hash=content_hash,
        )
        self._begin_document(report)
        position = {"bytes": 0}

        def texts() -> Iterator[str]:
            for text, done in blocks:
                position["bytes"] = done
                yield text

        def notify(stage: IngestStage) -> None:
            if progress:
                progress(stage, position["bytes"], report)

        try:
            batch: list[str] = []
            for chunk in chunk_blocks(texts(), self.chunk_size, self.chunk_overlap):
                batch.append(chunk)
                if len(batch) >= self.batch_size:
                    self._process_batch(report, batch, notify)
                    batch = []
                    if should_cancel and should_cancel():
                        raise IngestCancelled(title)
                    notify(IngestStage.PARSING)
            if batch:
                self._process_batch(report, batch, notify)
        except BaseException:
            self._rollback(document_id)
            raise

        self._complete_document(report)
        return report

    def _process_batch(
        self, report: IngestReport, batch: list[str], notify: Callable[[IngestStage], None]
    ) -> None:
        notify(IngestStage.SCREENING)
        kept: list[StoredChunk] = []
        allowed = denied = 0
        start = report.chunks_total
        for offset, text in enumerate(batch):
            index = start + offset
            chunk_id = f"{report.document_id}:{index}"
            verdict = self.firewall.scan(text, ContentChannel.RETRIEVED)
            if verdict.action == FirewallAction.BLOCK:
                denied += 1
                report.chunks_quarantined += 1
                self.firewall.record_incident(
                    verdict, context=f"ingest '{report.title}' from {report.source}"
                )
                self.trust.observe(
                    SubjectType.SOURCE,
                    report.source,
                    TrustSignal.INJECTED_CONTENT,
                    rationale=f"Injection in '{report.title}' chunk {index}",
                )
                self._record_quarantine(
                    report,
                    index,
                    text,
                    QuarantinedChunk(
                        chunk_id=chunk_id,
                        document_title=report.title,
                        source=report.source,
                        score=verdict.score,
                        categories=verdict.categories,
                        excerpt=text[:200],
                    ),
                )
                continue
            allowed += 1
            if verdict.action == FirewallAction.FLAG:
                report.chunks_flagged += 1
                text = self.firewall.sanitize(text, verdict)
                self.firewall.record_incident(
                    verdict, context=f"ingest '{report.title}' from {report.source}"
                )
                self.trust.observe(
                    SubjectType.SOURCE,
                    report.source,
                    TrustSignal.FIREWALL_FLAG,
                    rationale=f"Suspicious content in '{report.title}' chunk {index}",
                )
            kept.append(
                StoredChunk(
                    id=chunk_id,
                    document_id=report.document_id,
                    document_title=report.title,
                    source=report.source,
                    declared_trust=report.trust_level,
                    chunk_index=index,
                    content=text,
                    firewall_action=verdict.action,
                    firewall_score=verdict.score,
                )
            )
        get_audit_log().count_decisions("ingestion", allowed=allowed, denied=denied)
        report.chunks_total += len(batch)

        if kept:
            notify(IngestStage.EMBEDDING)
            vectors = self.embedder.embed([c.content for c in kept])
            notify(IngestStage.INDEXING)
            self.store.add(kept, vectors)
            report.chunks_indexed += len(kept)

    # Storage hooks — overridden by the Postgres knowledge base.
    def _begin_document(self, report: IngestReport) -> None:
        """Called before the first chunk of a document is processed."""

    def _record_quarantine(
        self, report: IngestReport, index: int, text: str, chunk: QuarantinedChunk
    ) -> None:
        with self._lock:
            self._quarantine.append(chunk)

    def _complete_document(self, report: IngestReport) -> None:
        with self._lock:
            self._documents[report.document_id] = report

    def _rollback(self, document_id: str) -> None:
        self.store.remove_document(document_id)
        prefix = f"{document_id}:"
        with self._lock:
            self._quarantine = [q for q in self._quarantine if not q.chunk_id.startswith(prefix)]

    # ------------------------------------------------------------ documents
    def documents(self) -> list[IngestReport]:
        with self._lock:
            return sorted(self._documents.values(), key=lambda d: d.created_at, reverse=True)

    def find_by_hash(self, content_hash: str) -> IngestReport | None:
        """The indexed document with this content, if there is one."""
        with self._lock:
            return next(
                (d for d in self._documents.values() if d.content_hash == content_hash), None
            )

    def document_chunks(self, document_id: str, limit: int = 50) -> list[DocumentChunkView]:
        return [
            DocumentChunkView(
                chunk_index=c.chunk_index,
                content=c.content,
                firewall_action=c.firewall_action,
                firewall_score=c.firewall_score,
            )
            for c in self.store.chunks_of(document_id, limit)
        ]

    def remove_document(self, document_id: str) -> bool:
        with self._lock:
            if document_id not in self._documents:
                return False
            del self._documents[document_id]
        self._rollback(document_id)
        self.save()
        return True

    # ------------------------------------------------------------ retrieval
    def retrieve(
        self,
        query: str,
        *,
        top_k: int | None = None,
        agent: str | None = None,
        session_id: str | None = None,
    ) -> RetrievalResult:
        """Return the most relevant chunks that pass every trust check."""
        k = min(top_k or self.top_k, self.policy.max_context_chunks)
        audit = get_audit_log()
        qvec = self.embedder.embed([query])[0]

        chunks: list[RetrievedChunk] = []
        dropped: list[DroppedChunk] = []
        for stored, similarity in self.store.search(qvec, k * 4):
            if len(chunks) >= k:
                break
            if similarity < self.policy.min_similarity:
                continue

            # Re-seed the source if the trust registry was reset.
            source_trust = self.trust.register_source(stored.source, stored.declared_trust)
            reason: str | None = None
            if (
                stored.declared_trust == TrustLevel.UNTRUSTED
                and not self.policy.allow_untrusted_sources
            ):
                reason = f"Source '{stored.source}' is UNTRUSTED."
            elif source_trust < self.policy.min_source_trust:
                reason = (
                    f"Source '{stored.source}' trust {source_trust:.2f} is below "
                    f"{self.policy.min_source_trust:.2f}."
                )

            content, sanitized = stored.content, stored.firewall_action == FirewallAction.FLAG
            if reason is None:
                verdict = self.firewall.inspect(
                    content,
                    ContentChannel.RETRIEVED,
                    agent=agent,
                    session_id=session_id,
                    context=f"retrieval from {stored.source}",
                )
                if verdict.action == FirewallAction.BLOCK:
                    reason = "Firewall blocked the chunk at retrieval."
                elif verdict.action == FirewallAction.FLAG:
                    content, sanitized = self.firewall.sanitize(content, verdict), True

            audit.log_decision(
                "rag", allowed=reason is None, subject=stored.source, agent=agent, reason=reason
            )
            if reason is not None:
                dropped.append(
                    DroppedChunk(
                        chunk_id=stored.id,
                        document_title=stored.document_title,
                        source=stored.source,
                        reason=reason,
                    )
                )
                continue
            chunks.append(
                RetrievedChunk(
                    chunk_id=stored.id,
                    document_title=stored.document_title,
                    source=stored.source,
                    source_trust=source_trust,
                    similarity=round(similarity, 4),
                    content=content,
                    sanitized=sanitized,
                )
            )
        return RetrievalResult(query=query, chunks=chunks, dropped=dropped)

    # ---------------------------------------------------------- persistence
    def save(self) -> None:
        """Write the index and document metadata to ``persist_dir`` (if enabled)."""
        if self.persist_dir is None:
            return
        with self._save_lock:
            self.store.save(self.persist_dir)
            with self._lock:
                meta = {
                    "embedder": self.embedder.name,
                    "documents": [d.model_dump(mode="json") for d in self._documents.values()],
                    "quarantine": [q.model_dump(mode="json") for q in self._quarantine],
                    "source_levels": {k: v.value for k, v in self._source_levels.items()},
                }
            tmp = self.persist_dir / "meta.tmp.json"
            tmp.write_text(json.dumps(meta), encoding="utf-8")
            os.replace(tmp, self.persist_dir / "meta.json")

    def seed_if_empty(self) -> None:
        """Load the saved index, or ingest the demo corpus if there is none."""
        if not self.load():
            seed_knowledge_base(self)

    def load(self) -> bool:
        """Load a saved index; False if none exists or it used another embedder."""
        if self.persist_dir is None or not (self.persist_dir / "meta.json").exists():
            return False
        meta = json.loads((self.persist_dir / "meta.json").read_text(encoding="utf-8"))
        if meta.get("embedder") != self.embedder.name:
            logger.warning(
                "index_embedder_mismatch", saved=meta.get("embedder"), current=self.embedder.name
            )
            return False
        if not self.store.load(self.persist_dir):
            return False
        with self._lock:
            self._documents = {
                d["document_id"]: IngestReport.model_validate(d) for d in meta["documents"]
            }
            self._quarantine = [QuarantinedChunk.model_validate(q) for q in meta["quarantine"]]
            self._source_levels = {k: TrustLevel(v) for k, v in meta["source_levels"].items()}
        return True

    # ---------------------------------------------------------------- stats
    def quarantine(self) -> list[QuarantinedChunk]:
        with self._lock:
            return list(self._quarantine)

    def stats(self) -> KnowledgeBaseStats:
        with self._lock:
            docs = list(self._documents.values())
            levels = dict(self._source_levels)
            quarantined = len(self._quarantine)
        per_source: dict[str, list[IngestReport]] = {}
        for d in docs:
            per_source.setdefault(d.source, []).append(d)
        summaries = []
        for source, items in sorted(per_source.items()):
            level = levels.get(source.lower(), items[0].trust_level)
            summaries.append(
                SourceSummary(
                    source=source,
                    trust_level=level,
                    trust_score=self.trust.register_source(source, level),
                    documents=len(items),
                    chunks_indexed=sum(d.chunks_indexed for d in items),
                )
            )
        return KnowledgeBaseStats(
            index_ready=len(self.store) > 0,
            embedder=self.embedder.name,
            documents=len(docs),
            bytes_ingested=sum(d.size_bytes for d in docs),
            chunks_screened=sum(d.chunks_total for d in docs),
            chunks_indexed=len(self.store),
            chunks_flagged=sum(d.chunks_flagged for d in docs),
            chunks_quarantined=quarantined,
            sources=[s.source for s in summaries],
            source_summaries=summaries,
            memory_bytes=self.store.memory_bytes(),
            persisted=self.persist_dir is not None,
        )


def seed_knowledge_base(kb: KnowledgeBase, seed_dir: Path = SEED_DIR) -> list[IngestReport]:
    """Ingest the demo corpus listed in ``seed/manifest.yaml``."""
    manifest = yaml.safe_load((seed_dir / "manifest.yaml").read_text(encoding="utf-8"))
    reports = []
    for entry in manifest["documents"]:
        path = seed_dir / entry["file"]
        reports.append(
            kb.ingest(
                IngestRequest(
                    title=entry["title"],
                    content=path.read_text(encoding="utf-8"),
                    source=entry["source"],
                    source_type=SourceType(entry.get("source_type", "FILE")),
                    trust_level=TrustLevel(entry["trust_level"]),
                    uri=entry.get("uri"),
                )
            )
        )
    return reports


@lru_cache
def get_knowledge_base() -> KnowledgeBase:
    """Return the process-wide knowledge base.

    In Postgres mode documents, chunks and embeddings live in pgvector tables.
    Otherwise the saved index in ``data/index`` is loaded when persistence is on.
    Either way the demo corpus is seeded the first time the store is empty.
    """
    settings = get_settings()
    kwargs: dict[str, Any] = {
        "embedder": get_embedder(),
        "firewall": get_firewall(),
        "trust": get_trust_engine(),
        "policy": get_global_config().rag,
        "chunk_size": settings.rag_chunk_size,
        "chunk_overlap": settings.rag_chunk_overlap,
        "top_k": settings.rag_top_k,
        "batch_size": settings.ingest_batch_size,
    }
    kb: KnowledgeBase
    if settings.use_postgres:
        from app.persistence.knowledge import PostgresKnowledgeBase

        kb = PostgresKnowledgeBase(**kwargs)
    else:
        kb = KnowledgeBase(
            **kwargs, persist_dir=settings.data_path("index") if settings.rag_persist else None
        )
    if settings.rag_seed_corpus:
        kb.seed_if_empty()
    elif not settings.use_postgres:
        kb.load()
    return kb

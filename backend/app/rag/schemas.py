"""Pydantic schemas for the RAG knowledge base."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from app.database.enums import SourceType, TrustLevel
from app.firewall.schemas import FirewallAction


def _now() -> datetime:
    return datetime.now(timezone.utc)


class StoredChunk(BaseModel):
    id: str
    document_id: str
    document_title: str
    source: str
    declared_trust: TrustLevel
    chunk_index: int
    content: str  # sanitized if the firewall flagged it at ingestion
    firewall_action: FirewallAction
    firewall_score: float


class IngestRequest(BaseModel):
    title: str = Field(max_length=512)
    content: str = Field(max_length=200_000)
    source: str = Field(max_length=255)
    source_type: SourceType = SourceType.MANUAL
    trust_level: TrustLevel = TrustLevel.UNTRUSTED
    uri: str | None = None


class IngestReport(BaseModel):
    """One ingested document and what the firewall did with its chunks."""

    document_id: str
    title: str
    source: str
    chunks_total: int
    chunks_indexed: int
    chunks_flagged: int
    chunks_quarantined: int
    trust_level: TrustLevel = TrustLevel.UNTRUSTED
    source_type: SourceType = SourceType.MANUAL
    filename: str | None = None
    size_bytes: int = 0
    # SHA-256 of the file (or pasted text): the same content is never indexed twice.
    content_hash: str | None = None
    created_at: datetime = Field(default_factory=_now)


class IngestStage(str, Enum):
    QUEUED = "QUEUED"
    PARSING = "PARSING"  # reading + chunking
    SCREENING = "SCREENING"  # firewall
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class IngestJob(BaseModel):
    """A background ingestion of one file, with live progress."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    filename: str
    title: str
    source: str
    trust_level: TrustLevel
    origin: str  # upload | inbox
    size_bytes: int
    bytes_read: int = 0
    stage: IngestStage = IngestStage.QUEUED
    chunks_total: int = 0
    chunks_indexed: int = 0
    chunks_flagged: int = 0
    chunks_quarantined: int = 0
    document_id: str | None = None
    # Set when the file's content was already indexed: the job completes without
    # indexing it again, and document_id points at the existing document.
    duplicate_of: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def done(self) -> bool:
        return self.stage in {IngestStage.COMPLETED, IngestStage.FAILED, IngestStage.CANCELLED}


class InboxFile(BaseModel):
    path: str  # relative to the inbox directory
    size_bytes: int
    supported: bool


class InboxListing(BaseModel):
    directory: str
    files: list[InboxFile]
    supported_extensions: list[str]


class InboxImportRequest(BaseModel):
    files: list[str] | None = None  # relative paths; None = every supported file
    source: str = Field(default="Inbox", max_length=255)
    trust_level: TrustLevel = TrustLevel.MEDIUM
    source_per_file: bool = True  # each file is its own trust source


class DocumentChunkView(BaseModel):
    chunk_index: int
    content: str
    firewall_action: FirewallAction
    firewall_score: float


class RetrievedChunk(BaseModel):
    chunk_id: str
    document_title: str
    source: str
    source_trust: float
    similarity: float
    content: str
    sanitized: bool = False


class DroppedChunk(BaseModel):
    chunk_id: str
    document_title: str
    source: str
    reason: str


class RetrievalResult(BaseModel):
    query: str
    chunks: list[RetrievedChunk]
    dropped: list[DroppedChunk] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)


class QuarantinedChunk(BaseModel):
    chunk_id: str
    document_title: str
    source: str
    score: float
    categories: list[str]
    excerpt: str


class SourceSummary(BaseModel):
    source: str
    trust_level: TrustLevel
    trust_score: float
    documents: int
    chunks_indexed: int


class KnowledgeBaseStats(BaseModel):
    index_ready: bool
    embedder: str
    documents: int
    bytes_ingested: int = 0
    chunks_screened: int = 0
    chunks_indexed: int
    chunks_flagged: int = 0
    chunks_quarantined: int
    sources: list[str]
    source_summaries: list[SourceSummary] = Field(default_factory=list)
    memory_bytes: int = 0
    persisted: bool = False

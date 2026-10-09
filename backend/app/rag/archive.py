"""Read-only archive projections. Eligibility is a source/ingestion snapshot,
not a promise that a chunk will pass the query-time similarity and firewall checks.
"""

from __future__ import annotations

import math
from typing import Any

from app.firewall.schemas import FirewallAction
from app.rag.knowledge_base import KnowledgeBase
from app.rag.schemas import ArchiveChunk, ArchiveChunkPage, ArchiveDocument


def archive_documents(kb: KnowledgeBase) -> list[ArchiveDocument]:
    result = []
    for report in kb.documents():
        score, reason = kb.source_gate(report.source, report.trust_level)
        result.append(
            ArchiveDocument(
                **report.model_dump(),
                source_trust=score,
                retrieval_allowed=reason is None,
                retrieval_reason=reason,
            )
        )
    return result


def chunk_view(entry: dict[str, Any], source_reason: str | None) -> ArchiveChunk:
    """One stored chunk with its status (ready / sanitized / low trust / blocked) and why."""
    if entry["firewall_action"] == FirewallAction.BLOCK:
        status = "blocked"
        reason = (
            "The ingestion firewall quarantined this chunk. It is not indexed or available to RAG."
        )
    elif source_reason:
        status, reason = "low", source_reason
    elif entry["firewall_action"] == FirewallAction.FLAG:
        status = "sanitized"
        reason = (
            "Flagged text was sanitized before indexing. "
            "The cleaned chunk passes the current source gate."
        )
    else:
        status = "ready"
        reason = "Ingestion screening passed and the source passes the current trust gate."
    characters = entry.get("characters")
    return ArchiveChunk(
        **entry,
        status=status,
        reason=reason,
        estimated_tokens=math.ceil(characters / 4) if characters is not None else None,
    )


def archive_chunks(
    kb: KnowledgeBase, document_id: str, offset: int, limit: int
) -> ArchiveChunkPage | None:
    report = kb.document(document_id)
    if report is None:
        return None
    _, source_reason = kb.source_gate(report.source, report.trust_level)
    chunks = [chunk_view(e, source_reason) for e in kb.archive_entries(document_id, offset, limit)]
    return ArchiveChunkPage(
        document_id=document_id,
        total=report.chunks_total,
        offset=offset,
        limit=limit,
        chunks=chunks,
        has_more=offset + limit < report.chunks_total,
    )

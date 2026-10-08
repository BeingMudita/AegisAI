"""Read-only projections of the vector index: what is stored, page by page,
and one vector in full with its nearest neighbours.
"""

from __future__ import annotations

import math

from app.firewall.schemas import FirewallAction
from app.rag.knowledge_base import KnowledgeBase
from app.rag.schemas import (
    IngestReport,
    StoredChunk,
    VectorDetail,
    VectorEntry,
    VectorIndexInfo,
    VectorNeighbour,
    VectorPage,
)

PREVIEW_CHARS = 240


def _entry(chunk: StoredChunk, report: IngestReport | None) -> VectorEntry:
    return VectorEntry(
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        document_title=report.title if report else chunk.document_title,
        section=report.section if report else "Unsorted",
        folder=report.folder if report else "General",
        source=report.source if report else chunk.source,
        chunk_index=chunk.chunk_index,
        preview=chunk.content[:PREVIEW_CHARS],
        characters=len(chunk.content),
        firewall_action=chunk.firewall_action,
        firewall_score=chunk.firewall_score,
    )


def _in_folder(report: IngestReport, folder: str) -> bool:
    return report.folder == folder or report.folder.startswith(folder + "/")


def vector_info(kb: KnowledgeBase) -> VectorIndexInfo:
    return VectorIndexInfo(
        backend=kb.backend_name,
        embedder=kb.embedder.name,
        dim=kb.embedder.dim,
        vectors=len(kb.store),
        documents=len(kb.documents()),
        size_bytes=kb.store.memory_bytes(),
        persisted=kb.backend_name == "pgvector" or kb.persist_dir is not None,
    )


def vector_page(
    kb: KnowledgeBase,
    *,
    section: str | None = None,
    folder: str | None = None,
    document_id: str | None = None,
    query: str | None = None,
    action: FirewallAction | None = None,
    offset: int = 0,
    limit: int = 25,
) -> VectorPage:
    """Indexed chunks in index order, narrowed to a document, folder or section."""
    reports = {d.document_id: d for d in kb.documents()}
    ids: set[str] | None = None
    if document_id:
        ids = {document_id}
    elif section:
        ids = {
            d
            for d, r in reports.items()
            if r.section == section and (not folder or _in_folder(r, folder))
        }
    total, chunks = kb.store.entries(
        document_ids=ids, query=query or None, action=action, offset=offset, limit=limit
    )
    return VectorPage(
        total=total,
        offset=offset,
        limit=limit,
        items=[_entry(c, reports.get(c.document_id)) for c in chunks],
        has_more=offset + limit < total,
    )


def vector_detail(kb: KnowledgeBase, chunk_id: str, neighbours: int = 5) -> VectorDetail | None:
    found = kb.store.get(chunk_id)
    if found is None:
        return None
    chunk, vector = found
    nearest = [
        VectorNeighbour(
            chunk_id=other.id,
            document_title=other.document_title,
            chunk_index=other.chunk_index,
            similarity=similarity,
            preview=other.content[:PREVIEW_CHARS],
        )
        for other, similarity in kb.store.search(vector, neighbours + 1)
        if other.id != chunk.id
    ][:neighbours]
    return VectorDetail(
        **_entry(chunk, kb.document(chunk.document_id)).model_dump(),
        content=chunk.content,
        model=kb.embedder.name,
        dim=len(vector),
        norm=math.sqrt(sum(x * x for x in vector)),
        vector=vector,
        neighbours=nearest,
    )

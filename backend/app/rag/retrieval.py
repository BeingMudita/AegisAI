"""Vector retrieval over pgvector.

Question → embedding → cosine vector search → top-K chunks.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.models import Document, DocumentChunk, DocumentSource, Embedding
from app.rag.embeddings import get_embedder
from app.rag.schemas import RetrievedChunk

settings = get_settings()


async def retrieve(
    session: AsyncSession,
    query: str,
    *,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    """Embed ``query`` and return the top-K most similar chunks."""
    k = top_k or settings.rag_top_k
    embedder = get_embedder()
    query_vec = embedder.embed_text(query)

    # cosine_distance = 1 - cosine_similarity; smaller is closer.
    distance = Embedding.vector.cosine_distance(query_vec).label("distance")

    stmt = (
        select(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentChunk.chunk_index,
            DocumentChunk.content,
            Document.title,
            DocumentSource.name,
            distance,
        )
        .join(Embedding, Embedding.chunk_id == DocumentChunk.id)
        .join(Document, Document.id == DocumentChunk.document_id)
        .outerjoin(DocumentSource, DocumentSource.id == Document.source_id)
        .order_by(distance.asc())
        .limit(k)
    )

    rows = (await session.execute(stmt)).all()

    results: list[RetrievedChunk] = []
    for chunk_id, doc_id, idx, content, title, source_name, dist in rows:
        results.append(
            RetrievedChunk(
                chunk_id=str(chunk_id),
                document_id=str(doc_id),
                document_title=title,
                source=source_name,
                chunk_index=idx,
                content=content,
                score=round(1.0 - float(dist), 6),
            )
        )
    return results

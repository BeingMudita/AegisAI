"""Document ingestion: PDF/TXT/MD → text → chunks → embeddings → PostgreSQL.

Run from the ``backend`` directory after the DB is initialized:

    python -m app.rag.ingest ../data
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.enums import SourceType
from app.database.models import Document, DocumentChunk, DocumentSource, Embedding
from app.database.session import get_engine, get_sessionmaker
from app.rag.chunking import chunk_text
from app.rag.embeddings import get_embedder
from app.rag.extraction import SUPPORTED_SUFFIXES, extract_text

settings = get_settings()


@dataclass
class IngestSummary:
    documents: int = 0
    chunks: int = 0
    skipped: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        skipped = f", skipped {len(self.skipped)}" if self.skipped else ""
        return f"Ingested {self.documents} documents, {self.chunks} chunks{skipped}."


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _get_or_create_source(session: AsyncSession, name: str) -> DocumentSource:
    existing = (
        await session.execute(select(DocumentSource).where(DocumentSource.name == name))
    ).scalar_one_or_none()
    if existing:
        return existing
    source = DocumentSource(name=name, type=SourceType.FILE)
    session.add(source)
    await session.flush()
    return source


async def ingest_file(
    session: AsyncSession, path: Path, source: DocumentSource
) -> tuple[bool, int]:
    """Ingest a single file. Returns (created, n_chunks). Skips duplicates."""
    text = extract_text(path)
    if not text.strip():
        return False, 0

    content_hash = _hash(text)
    dup = (
        await session.execute(
            select(Document).where(Document.content_hash == content_hash)
        )
    ).scalar_one_or_none()
    if dup:
        return False, 0

    document = Document(
        source_id=source.id,
        title=path.stem,
        uri=str(path),
        content_hash=content_hash,
        meta={"filename": path.name},
    )
    session.add(document)
    await session.flush()

    chunks = chunk_text(
        text,
        chunk_size=settings.rag_chunk_size,
        overlap=settings.rag_chunk_overlap,
    )
    if not chunks:
        return True, 0

    embedder = get_embedder()
    vectors = embedder.embed_batch([c.content for c in chunks])

    for chunk, vector in zip(chunks, vectors, strict=True):
        db_chunk = DocumentChunk(
            document_id=document.id,
            chunk_index=chunk.index,
            content=chunk.content,
            token_count=len(chunk.content.split()),
        )
        session.add(db_chunk)
        await session.flush()
        session.add(
            Embedding(chunk_id=db_chunk.id, model=embedder.model_name, vector=vector)
        )

    return True, len(chunks)


async def ingest_directory(session: AsyncSession, root: Path) -> IngestSummary:
    """Walk ``root``, ingesting every supported file.

    The immediate parent folder name becomes the document source (e.g.
    ``invoices``, ``company_policies``, ``emails``).
    """
    summary = IngestSummary()
    files = sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    )
    for path in files:
        source_name = path.parent.name or root.name
        source = await _get_or_create_source(session, source_name)
        try:
            created, n = await ingest_file(session, path, source)
        except Exception as exc:  # noqa: BLE001
            summary.skipped.append(f"{path.name}: {exc}")
            continue
        if created:
            summary.documents += 1
            summary.chunks += n
        else:
            summary.skipped.append(f"{path.name}: duplicate/empty")
    return summary


async def _main(root: str) -> None:
    root_path = Path(root).resolve()
    if not root_path.exists():
        raise SystemExit(f"Path not found: {root_path}")

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        summary = await ingest_directory(session, root_path)
        await session.commit()
    await get_engine().dispose()
    print(summary)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "../data"
    asyncio.run(_main(target))

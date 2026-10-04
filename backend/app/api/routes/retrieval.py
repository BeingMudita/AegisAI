"""Retrieval routes — guarded search over the knowledge base, and data ingestion.

Searching is open to any principal; adding or deleting data is ADMIN only;
viewing documents, jobs and the quarantine is staff only.

Two ways to add files:
  * POST /retrieval/uploads        — multipart upload from the dashboard
  * POST /retrieval/inbox/import   — files already copied into data/inbox/
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.auth.dependencies import get_current_user, require_roles
from app.auth.roles import STAFF_ROLES, Role
from app.auth.schemas import User
from app.config import get_settings
from app.database.enums import TrustLevel
from app.rag.ingestion import get_ingestion_manager
from app.rag.knowledge_base import get_knowledge_base
from app.rag.parsers import SUPPORTED_EXTENSIONS, is_supported
from app.rag.schemas import (
    DocumentChunkView,
    InboxImportRequest,
    InboxListing,
    IngestJob,
    IngestReport,
    IngestRequest,
    KnowledgeBaseStats,
    QuarantinedChunk,
    RetrievalResult,
    SearchRequest,
)

router = APIRouter(prefix="/retrieval", tags=["retrieval"])
_COPY_CHUNK = 1024 * 1024


@router.get("", response_model=KnowledgeBaseStats)
def retrieval_status(user: User = Depends(get_current_user)) -> KnowledgeBaseStats:
    """Knowledge-base status and pipeline counters."""
    return get_knowledge_base().stats()


@router.post("/search", response_model=RetrievalResult)
def search(req: SearchRequest, user: User = Depends(get_current_user)) -> RetrievalResult:
    """Retrieve the chunks that pass every trust and firewall check."""
    return get_knowledge_base().retrieve(req.query, top_k=req.top_k, agent=user.username)


# ------------------------------------------------------------------ documents
@router.get("/documents", response_model=list[IngestReport])
def list_documents(user: User = Depends(require_roles(*STAFF_ROLES))) -> list[IngestReport]:
    """Every ingested document, newest first."""
    return get_knowledge_base().documents()


@router.post("/documents", response_model=IngestReport, status_code=201)
def ingest_document(
    req: IngestRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
) -> IngestReport:
    """Screen, chunk, embed and index pasted text."""
    return get_knowledge_base().ingest(req)


@router.get("/documents/{document_id}/chunks", response_model=list[DocumentChunkView])
def document_chunks(
    document_id: str, user: User = Depends(require_roles(*STAFF_ROLES))
) -> list[DocumentChunkView]:
    """The first chunks of a document as they were indexed (after sanitizing)."""
    return get_knowledge_base().document_chunks(document_id)


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str, user: User = Depends(require_roles(Role.ADMIN))) -> None:
    """Remove a document and all of its chunks from the index."""
    if not get_knowledge_base().remove_document(document_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")


# -------------------------------------------------------------------- uploads
@router.post("/uploads", response_model=list[IngestJob], status_code=202)
def upload_files(
    files: list[UploadFile] = File(...),
    source: str = Form("Uploads"),
    trust_level: TrustLevel = Form(TrustLevel.MEDIUM),
    source_per_file: bool = Form(True),
    user: User = Depends(require_roles(Role.ADMIN)),
) -> list[IngestJob]:
    """Upload files; each becomes a background ingestion job.

    With ``source_per_file`` each file is its own trust source, so one poisoned
    file can't drag down the trust of the clean files uploaded with it.
    """
    manager = get_ingestion_manager()
    limit = get_settings().max_upload_mb * 1024 * 1024
    jobs = []
    for upload in files:
        name = (upload.filename or "upload").replace("\\", "/").rsplit("/", 1)[-1]
        if not is_supported(name):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"'{name}' is not a supported type ({', '.join(SUPPORTED_EXTENSIONS)}).",
            )
        target = manager.upload_dir / f"{uuid.uuid4().hex[:8]}-{name}"
        written = 0
        with target.open("wb") as out:
            while block := upload.file.read(_COPY_CHUNK):
                written += len(block)
                if written > limit:
                    out.close()
                    target.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"'{name}' exceeds {get_settings().max_upload_mb} MB; "
                        "copy large files into the inbox folder instead.",
                    )
                out.write(block)
        jobs.append(
            manager.submit(
                target,
                title=name,
                source=name if source_per_file else source,
                trust_level=trust_level,
                origin="upload",
                delete_after=True,
                filename=name,
            )
        )
    return jobs


# ---------------------------------------------------------------------- inbox
@router.get("/inbox", response_model=InboxListing)
def list_inbox(user: User = Depends(require_roles(Role.ADMIN))) -> InboxListing:
    """Files waiting in the server-side inbox folder."""
    return get_ingestion_manager().list_inbox()


@router.post("/inbox/import", response_model=list[IngestJob], status_code=202)
def import_inbox(
    req: InboxImportRequest, user: User = Depends(require_roles(Role.ADMIN))
) -> list[IngestJob]:
    """Queue inbox files (all supported ones by default) for ingestion."""
    try:
        return get_ingestion_manager().import_inbox(
            req.files,
            source=req.source,
            trust_level=req.trust_level,
            source_per_file=req.source_per_file,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Not in the inbox: {exc}"
        ) from exc


# ----------------------------------------------------------------------- jobs
@router.get("/jobs", response_model=list[IngestJob])
def list_jobs(user: User = Depends(require_roles(*STAFF_ROLES))) -> list[IngestJob]:
    """Ingestion jobs, newest first, with live progress."""
    return get_ingestion_manager().list_jobs()


@router.post("/jobs/{job_id}/cancel", response_model=IngestJob)
def cancel_job(job_id: str, user: User = Depends(require_roles(Role.ADMIN))) -> IngestJob:
    job = get_ingestion_manager().cancel(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return job


@router.get("/quarantine", response_model=list[QuarantinedChunk])
def quarantine(user: User = Depends(require_roles(*STAFF_ROLES))) -> list[QuarantinedChunk]:
    """Chunks the firewall refused to index."""
    return get_knowledge_base().quarantine()

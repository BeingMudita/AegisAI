"""Retrieval routes — guarded search over the knowledge base, and data ingestion.

Searching is open to any principal; adding or deleting data is ADMIN only;
viewing documents, jobs and the quarantine is staff only.

Two ways to add files:
  * POST /retrieval/uploads        — multipart upload from the dashboard
  * POST /retrieval/inbox/import   — files already copied into data/inbox/
"""

from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.auth.dependencies import get_current_user, require_roles
from app.auth.roles import STAFF_ROLES, Role
from app.auth.schemas import User
from app.config import get_settings
from app.database.enums import TrustLevel
from app.rag.archive import archive_chunks, archive_documents
from app.rag.ingestion import get_ingestion_manager
from app.rag.knowledge_base import DuplicateDocument, get_knowledge_base
from app.rag.parsers import SUPPORTED_EXTENSIONS, is_supported
from app.rag.paths import archive_location, file_source, normalize_relative_path
from app.rag.review import forget_count
from app.rag.schemas import (
    ArchiveChunkPage,
    ArchiveDocument,
    ArchiveLocation,
    DeleteDocumentsRequest,
    DeleteDocumentsResult,
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
@router.get("/archive", response_model=list[ArchiveDocument])
def archive(user: User = Depends(require_roles(*STAFF_ROLES))) -> list[ArchiveDocument]:
    return archive_documents(get_knowledge_base())


@router.get("/documents/{document_id}/archive-chunks", response_model=ArchiveChunkPage)
def archive_document_chunks(
    document_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(12, ge=1, le=50),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> ArchiveChunkPage:
    page = archive_chunks(get_knowledge_base(), document_id, offset, limit)
    if page is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return page


@router.put("/documents/{document_id}/location", response_model=IngestReport)
def organize_document(
    document_id: str,
    location: ArchiveLocation,
    user: User = Depends(require_roles(Role.ADMIN)),
) -> IngestReport:
    report = get_knowledge_base().move_document(document_id, location)
    if report is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return report


@router.get("/documents", response_model=list[IngestReport])
def list_documents(user: User = Depends(require_roles(*STAFF_ROLES))) -> list[IngestReport]:
    """Every ingested document, newest first."""
    return get_knowledge_base().documents()


@router.post("/documents", response_model=IngestReport, status_code=201)
def ingest_document(
    req: IngestRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
) -> IngestReport:
    """Screen, chunk, embed and index pasted text (409 if it is already indexed)."""
    try:
        return get_knowledge_base().ingest(req)
    except DuplicateDocument as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


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


@router.post("/documents/delete", response_model=DeleteDocumentsResult)
def delete_documents(
    req: DeleteDocumentsRequest, user: User = Depends(require_roles(Role.ADMIN))
) -> DeleteDocumentsResult:
    """Remove several documents (a selection, a folder, a section) in one request."""
    deleted = get_knowledge_base().remove_documents(req.document_ids)
    forget_count()
    removed = set(deleted)
    missing = [d for d in dict.fromkeys(req.document_ids) if d not in removed]
    return DeleteDocumentsResult(deleted=deleted, missing=missing)


# -------------------------------------------------------------------- uploads
@router.post("/uploads", response_model=list[IngestJob], status_code=202)
def upload_files(
    files: list[UploadFile] = File(...),
    source: str = Form("Uploads"),
    trust_level: TrustLevel = Form(TrustLevel.MEDIUM),
    source_per_file: bool = Form(True),
    section: str = Form("Unsorted", min_length=1, max_length=80),
    folder: str = Form("General", min_length=1, max_length=1024),
    relative_paths: list[str] | None = Form(None),
    user: User = Depends(require_roles(Role.ADMIN)),
) -> list[IngestJob]:
    """Upload files; each becomes a background ingestion job.

    With ``source_per_file`` each file is its own trust source, so one poisoned
    file can't drag down the trust of the clean files uploaded with it.
    """
    manager = get_ingestion_manager()
    if not section.strip() or not folder.strip():
        raise HTTPException(status_code=422, detail="Section and folder cannot be blank.")
    if relative_paths is not None and len(relative_paths) != len(files):
        raise HTTPException(status_code=422, detail="Each file needs one relative path.")
    prepared = []
    # Validate the entire batch before creating files or queuing any jobs.
    for index, upload in enumerate(files):
        name = (upload.filename or "upload").replace("\\", "/").rsplit("/", 1)[-1]
        try:
            relative = normalize_relative_path(relative_paths[index] if relative_paths else name)
            if relative.rsplit("/", 1)[-1] != name:
                raise ValueError("The relative path must end with the uploaded file name.")
            location = archive_location(relative, section.strip(), folder.strip())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not is_supported(name):
            raise HTTPException(
                status_code=415,
                detail=f"'{name}' is not a supported type ({', '.join(SUPPORTED_EXTENSIONS)}).",
            )
        if upload.size is not None and upload.size > get_settings().max_upload_mb * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"'{name}' exceeds the upload size limit.")
        prepared.append((upload, name, relative, location))
    limit = get_settings().max_upload_mb * 1024 * 1024
    jobs = []
    for upload, name, relative, location in prepared:
        target = manager.upload_dir / f"{uuid.uuid4().hex}.{name.rsplit('.', 1)[-1]}"
        written = 0
        digest = hashlib.sha256()  # hashed while copying, for duplicate detection
        with target.open("wb") as out:
            while block := upload.file.read(_COPY_CHUNK):
                written += len(block)
                digest.update(block)
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
                source=file_source(relative) if source_per_file else source,
                trust_level=trust_level,
                origin="upload",
                delete_after=True,
                filename=relative,
                content_hash=digest.hexdigest(),
                section=location.section,
                folder=location.folder,
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
            section=req.section,
            folder=req.folder,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Not in the inbox: {exc}"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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

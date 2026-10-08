"""Vector index routes — browse the stored embeddings and edit single chunks.

Reading is for staff (ADMIN, SECURITY_ANALYST); changes are ADMIN only. An
edited chunk goes through the ingestion firewall and is re-embedded, so the
index never holds text that skipped screening or a vector that doesn't match
its text.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.dependencies import require_roles
from app.auth.roles import STAFF_ROLES, Role
from app.auth.schemas import User
from app.firewall.schemas import FirewallAction
from app.rag.knowledge_base import ChunkRejected, get_knowledge_base
from app.rag.schemas import (
    VectorDetail,
    VectorEditRequest,
    VectorEditResult,
    VectorIndexInfo,
    VectorPage,
)
from app.rag.vectors import vector_detail, vector_info, vector_page

router = APIRouter(prefix="/vectors", tags=["vectors"])


@router.get("/info", response_model=VectorIndexInfo)
def info(user: User = Depends(require_roles(*STAFF_ROLES))) -> VectorIndexInfo:
    return vector_info(get_knowledge_base())


@router.get("", response_model=VectorPage)
def list_vectors(
    section: str | None = Query(None, max_length=80),
    folder: str | None = Query(None, max_length=1024),
    document_id: str | None = Query(None, max_length=64),
    q: str | None = Query(None, max_length=200),
    action: FirewallAction | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> VectorPage:
    """Indexed chunks in index order. ``q`` matches the chunk text."""
    return vector_page(
        get_knowledge_base(),
        section=section,
        folder=folder,
        document_id=document_id,
        query=q,
        action=action,
        offset=offset,
        limit=limit,
    )


@router.get("/{chunk_id}", response_model=VectorDetail)
def get_vector(chunk_id: str, user: User = Depends(require_roles(*STAFF_ROLES))) -> VectorDetail:
    """One vector in full, with its nearest neighbours in the index."""
    detail = vector_detail(get_knowledge_base(), chunk_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vector not found.")
    return detail


@router.put("/{chunk_id}", response_model=VectorEditResult)
def edit_vector(
    chunk_id: str, req: VectorEditRequest, user: User = Depends(require_roles(Role.ADMIN))
) -> VectorEditResult:
    """Replace a chunk's text: screened by the firewall, then re-embedded."""
    kb = get_knowledge_base()
    try:
        result = kb.edit_chunk(chunk_id, req.content, edited_by=user.username)
    except ChunkRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    detail = vector_detail(kb, chunk_id) if result else None
    if result is None or detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vector not found.")
    _, verdict = result
    return VectorEditResult(
        detail=detail,
        sanitized=verdict.action == FirewallAction.FLAG,
        categories=verdict.categories,
    )


@router.delete("/{chunk_id}", status_code=204)
def delete_vector(chunk_id: str, user: User = Depends(require_roles(Role.ADMIN))) -> None:
    """Remove one chunk and its vector from the index (the document stays)."""
    if not get_knowledge_base().remove_chunk(chunk_id, removed_by=user.username):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vector not found.")

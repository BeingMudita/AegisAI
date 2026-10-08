"""Approval routes — the human-in-the-loop queues.

Two queues: high-impact tool calls (approving re-runs every gateway checkpoint
before the tool executes) and documents whose screening found something
(blocked or sanitized chunks, an untrusted source) for a person to sign off.
Staff (ADMIN, SECURITY_ANALYST) can see both; only ADMIN can decide.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.dependencies import require_roles
from app.auth.roles import STAFF_ROLES, Role
from app.auth.schemas import User
from app.config import get_settings
from app.rag.knowledge_base import get_knowledge_base
from app.rag.review import attention_count, forget_count, review_findings, review_queue
from app.rag.schemas import (
    ArchiveChunk,
    DocumentReviewPage,
    ReviewDecision,
    ReviewKind,
    ReviewResult,
)
from app.tools.gateway import ApprovalError, get_tool_gateway
from app.tools.schemas import ApprovalQueue, ReviewRequest, ToolCallResult

router = APIRouter(prefix="/approvals", tags=["approvals"])
logger = structlog.get_logger("aegisai.approvals")


def _error(exc: ApprovalError) -> HTTPException:
    code = status.HTTP_404_NOT_FOUND if exc.not_found else status.HTTP_409_CONFLICT
    return HTTPException(status_code=code, detail=str(exc))


@router.get("", response_model=ApprovalQueue)
def approval_queue(user: User = Depends(require_roles(*STAFF_ROLES))) -> ApprovalQueue:
    """Requests waiting for a decision, and recently decided ones."""
    pending, recent = get_tool_gateway().approval_queue()
    return ApprovalQueue(
        pending=pending, recent=recent, ttl_minutes=get_settings().approval_ttl_minutes
    )


@router.get("/pending-count")
def pending_count(user: User = Depends(require_roles(*STAFF_ROLES))) -> dict[str, int]:
    """What waits for a person (a cheap poll for the navigation badge): tool calls,
    plus documents with blocked chunks or an untrusted source."""
    tools = get_tool_gateway().pending_count()
    documents = attention_count(get_knowledge_base())
    return {"pending": tools + documents, "tools": tools, "documents": documents}


# Declared before "/{request_id}/…" so "documents" is never read as a request id.
@router.get("/documents", response_model=DocumentReviewPage)
def document_reviews(
    kind: ReviewKind | None = None,
    review_status: str = Query("pending", alias="status", pattern="^(pending|approved)$"),
    q: str | None = Query(None, max_length=200),
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> DocumentReviewPage:
    """Documents whose screening found something, most urgent first."""
    return review_queue(
        get_knowledge_base(), kind=kind, status=review_status, query=q, offset=offset, limit=limit
    )


@router.get("/documents/{document_id}/findings", response_model=list[ArchiveChunk])
def document_findings(
    document_id: str, user: User = Depends(require_roles(*STAFF_ROLES))
) -> list[ArchiveChunk]:
    """The blocked and sanitized chunks behind a review."""
    findings = review_findings(get_knowledge_base(), document_id)
    if findings is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return findings


@router.post("/documents/approve", response_model=ReviewResult)
def approve_documents(
    body: ReviewDecision, user: User = Depends(require_roles(Role.ADMIN))
) -> ReviewResult:
    """Keep these documents as screened and record the sign-off. To reject one,
    delete it (``POST /api/retrieval/documents/delete``)."""
    approved = get_knowledge_base().mark_reviewed(
        body.document_ids, reviewed_by=user.username, note=body.note
    )
    forget_count()
    logger.info("documents_reviewed", by=user.username, approved=len(approved))
    found = set(approved)
    missing = [d for d in dict.fromkeys(body.document_ids) if d not in found]
    return ReviewResult(approved=approved, missing=missing)


@router.post("/{request_id}/approve", response_model=ToolCallResult)
def approve(
    request_id: str,
    body: ReviewRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
) -> ToolCallResult:
    """Approve a request: every checkpoint is re-verified, then the tool runs."""
    try:
        return get_tool_gateway().approve(request_id, user.username, body.note)
    except ApprovalError as exc:
        raise _error(exc) from exc


@router.post("/{request_id}/reject", response_model=ToolCallResult)
def reject(
    request_id: str,
    body: ReviewRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
) -> ToolCallResult:
    """Reject a request; the agent takes a small trust penalty."""
    try:
        return get_tool_gateway().reject(request_id, user.username, body.note)
    except ApprovalError as exc:
        raise _error(exc) from exc

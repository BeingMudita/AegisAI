"""Approval routes — the human-in-the-loop queue for high-impact tool calls.

Staff (ADMIN, SECURITY_ANALYST) can see the queue; only ADMIN can decide.
Approving re-runs every gateway checkpoint before the tool executes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import require_roles
from app.auth.roles import STAFF_ROLES, Role
from app.auth.schemas import User
from app.config import get_settings
from app.tools.gateway import ApprovalError, get_tool_gateway
from app.tools.schemas import ApprovalQueue, ReviewRequest, ToolCallResult

router = APIRouter(prefix="/approvals", tags=["approvals"])


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

"""Sessions routes — agent conversation/session lifecycle.

Phase 1 stubs; wired to the database and agent orchestration in later phases.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.auth.schemas import User

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("")
async def list_sessions(user: User = Depends(get_current_user)) -> dict:
    """List sessions visible to the caller (placeholder)."""
    return {"sessions": [], "requested_by": user.username}

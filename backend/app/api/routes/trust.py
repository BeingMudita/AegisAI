"""Trust routes — inspect trust scores for actors, sources, and tools.

Restricted to staff (ADMIN, SECURITY_ANALYST). Phase 1 stubs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import require_roles
from app.auth.roles import STAFF_ROLES
from app.auth.schemas import User

router = APIRouter(prefix="/trust", tags=["trust"])


@router.get("")
async def list_trust_scores(
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict:
    """List current trust scores (placeholder)."""
    return {"scores": [], "threshold": None}

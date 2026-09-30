"""Tools routes — the registry of permissioned agent tools.

Read access for staff; mutations will require ADMIN. Phase 1 stubs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import require_roles
from app.auth.roles import STAFF_ROLES
from app.auth.schemas import User

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("")
async def list_tools(
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict:
    """List registered tools (placeholder)."""
    return {"tools": []}

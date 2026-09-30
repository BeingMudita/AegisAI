"""Security-events routes — audit log of firewall/trust/policy decisions.

Restricted to staff (ADMIN, SECURITY_ANALYST). Phase 1 stubs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import require_roles
from app.auth.roles import STAFF_ROLES
from app.auth.schemas import User

router = APIRouter(prefix="/security-events", tags=["security-events"])


@router.get("")
async def list_security_events(
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict:
    """List recorded security events (placeholder)."""
    return {"events": [], "count": 0}

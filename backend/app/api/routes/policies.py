"""Policies routes — view and (later) manage declarative agent policies.

Read access for staff; write access for ADMIN only. Phase 1 stubs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import require_roles
from app.auth.roles import STAFF_ROLES, Role
from app.auth.schemas import User

router = APIRouter(prefix="/policies", tags=["policies"])


@router.get("")
async def list_policies(
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict:
    """List active policies (placeholder)."""
    return {"policies": [], "source": "default_policies.yaml"}


@router.post("", status_code=201)
async def create_policy(
    user: User = Depends(require_roles(Role.ADMIN)),
) -> dict:
    """Create a policy (placeholder, ADMIN only)."""
    return {"created": False, "detail": "not_implemented"}

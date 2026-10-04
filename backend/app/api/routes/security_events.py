"""Security-events routes — audit log of firewall/trust/policy decisions.

Restricted to staff (ADMIN, SECURITY_ANALYST).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.dependencies import require_roles
from app.auth.roles import STAFF_ROLES, Role
from app.auth.schemas import User
from app.database.enums import SecurityEventType, SecuritySeverity
from app.telemetry.schemas import TelemetrySummary
from app.telemetry.store import get_audit_log

router = APIRouter(prefix="/security-events", tags=["security-events"])


@router.get("")
async def list_security_events(
    event_type: SecurityEventType | None = None,
    severity: SecuritySeverity | None = None,
    agent: str | None = None,
    session_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict:
    """List recorded security events, newest first."""
    events = get_audit_log().list_events(
        event_type=event_type,
        severity=severity,
        agent=agent,
        session_id=session_id,
        limit=limit,
    )
    return {"events": [e.model_dump(mode="json") for e in events], "count": len(events)}


@router.get("/summary", response_model=TelemetrySummary)
async def summary(
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> TelemetrySummary:
    """Aggregate event and decision counts for the dashboard."""
    return get_audit_log().summary()


@router.delete("", status_code=204)
async def clear_events(user: User = Depends(require_roles(Role.ADMIN))) -> None:
    """Clear the in-memory audit buffer (ADMIN only).

    The durable (Postgres) audit log refuses: it is pruned only by retention.
    """
    try:
        get_audit_log().clear()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

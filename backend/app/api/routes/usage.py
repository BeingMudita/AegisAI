"""Usage routes: each principal's daily budget and what has been used of it."""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.auth.dependencies import get_current_user, require_roles
from app.auth.roles import STAFF_ROLES
from app.auth.schemas import User
from app.quotas.service import BudgetStatus, get_quota_service
from app.quotas.store import UsageRecord

router = APIRouter(prefix="/usage", tags=["usage"])


class UsagePage(BaseModel):
    day: date
    records: list[UsageRecord]
    total: int
    next_offset: int | None


@router.get("/me", response_model=BudgetStatus)
def my_budget(user: User = Depends(get_current_user)) -> BudgetStatus:
    """The caller's limits for today and how much of them is used."""
    return get_quota_service().status(user.username)


@router.get("", response_model=UsagePage)
def usage(
    day: date | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> UsagePage:
    """Every principal's consumption on ``day`` (default today, UTC), heaviest first."""
    day = day or datetime.now(timezone.utc).date()
    records, total = get_quota_service().store.list(day, limit=limit, offset=offset)
    more = offset + len(records) < total
    return UsagePage(
        day=day, records=records, total=total, next_offset=offset + len(records) if more else None
    )

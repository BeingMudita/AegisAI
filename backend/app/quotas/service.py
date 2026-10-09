"""Enforce per-principal budgets around agent turns.

A turn is *reserved* before it runs — atomically counted against the day's
turn limit, and refused if any limit (turns, tokens, cost) is already used up —
and *charged* when it finishes, with the tokens the LLM reported and their cost.
A turn that starts with budget left may finish over it; ``max_output_tokens``
caps how far, and the next turn is refused.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache

from pydantic import BaseModel

from app.database.enums import SecurityEventType, SecuritySeverity
from app.policies.config import BudgetLimits, BudgetPolicy, get_global_config
from app.quotas.store import BudgetStore, UsageRecord, exceeded, get_budget_store
from app.quotas.usage import TokenUsage
from app.telemetry.store import get_audit_log


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _resets_at(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=timezone.utc)


class BudgetStatus(BaseModel):
    principal: str
    limits: BudgetLimits
    used: UsageRecord
    exhausted: str | None  # the limit used up, if any
    resets_at: datetime


class BudgetExceeded(Exception):
    """A principal has used up one of its daily limits."""

    def __init__(self, status: BudgetStatus) -> None:
        self.status = status
        self.retry_after = max(1, math.ceil((status.resets_at - _now()).total_seconds()))
        names = {"turns": "turn", "tokens": "token", "cost": "cost"}
        super().__init__(
            f"Daily {names.get(status.exhausted or '', 'usage')} budget used up for "
            f"'{status.principal}'. It resets at {status.resets_at:%H:%M} UTC."
        )


class QuotaService:
    def __init__(self, store: BudgetStore, policy: BudgetPolicy | None = None) -> None:
        self.store = store
        self._policy = policy

    @property
    def policy(self) -> BudgetPolicy:
        return self._policy or get_global_config().budgets

    def limits(self, principal: str) -> BudgetLimits:
        from app.auth.users import get_user  # late: the user store may need the database

        user = get_user(principal)
        role = user.role.value if user is not None else None
        return self.policy.limits_for(principal, role)

    def status(self, principal: str) -> BudgetStatus:
        day = _now().date()
        limits = self.limits(principal)
        used = self.store.get(principal, day)
        return BudgetStatus(
            principal=principal,
            limits=limits,
            used=used,
            exhausted=exceeded(used, limits),
            resets_at=_resets_at(day),
        )

    def check(self, principal: str) -> None:
        """Raise :class:`BudgetExceeded` if ``principal`` has no budget left (counts nothing)."""
        status = self.status(principal)
        if status.exhausted:
            raise BudgetExceeded(status)

    def start_turn(self, principal: str, *, agent: str | None = None) -> None:
        """Reserve a turn for ``principal``, or raise :class:`BudgetExceeded`."""
        day = _now().date()
        limits = self.limits(principal)
        reservation = self.store.reserve(principal, day, limits)
        audit = get_audit_log()
        audit.log_decision(
            "quota",
            allowed=reservation.refused is None,
            subject="start a turn",
            agent=agent,
            reason=f"{principal}: {reservation.refused} budget used up"
            if reservation.refused
            else None,
        )
        if reservation.refused is None:
            return
        status = BudgetStatus(
            principal=principal,
            limits=limits,
            used=reservation.record,
            exhausted=reservation.refused,
            resets_at=_resets_at(day),
        )
        if reservation.first_refusal:  # one event per principal per day, not one per retry
            audit.record_event(
                event_type=SecurityEventType.ANOMALY,
                severity=SecuritySeverity.MEDIUM,
                source="quota",
                agent=agent,
                description=f"Daily {reservation.refused} budget used up by '{principal}'.",
                details={
                    "principal": principal,
                    "limit": reservation.refused,
                    "limits": limits.model_dump(),
                    "used": reservation.record.model_dump(mode="json"),
                },
            )
        raise BudgetExceeded(status)

    def finish_turn(self, principal: str, usage: TokenUsage) -> TokenUsage:
        """Charge a finished turn's tokens and their cost; returns ``usage`` with the cost."""
        pricing = self.policy.pricing
        cost = (
            usage.prompt_tokens * pricing.prompt_per_1k
            + usage.completion_tokens * pricing.completion_per_1k
        ) / 1000
        charged = usage.model_copy(update={"cost_usd": round(cost, 6)})
        self.store.charge(principal, _now().date(), charged)
        return charged


@lru_cache
def get_quota_service() -> QuotaService:
    return QuotaService(get_budget_store())

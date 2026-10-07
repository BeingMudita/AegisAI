"""Durable budget counters: ``usage_budgets`` (one row per principal per UTC day).

Reservation locks the principal's row for the day (``SELECT … FOR UPDATE``), so
concurrent turns on any worker are counted exactly against the turn limit.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.database.models import UsageBudget
from app.database.sync import transaction
from app.policies.config import BudgetLimits
from app.quotas.store import BudgetStore, Reservation, UsageRecord, exceeded
from app.quotas.usage import TokenUsage


def _record(row: UsageBudget) -> UsageRecord:
    return UsageRecord(
        principal=row.principal,
        day=row.day,
        turns=row.turns,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        tokens=row.tokens,
        cost_usd=row.cost_usd,
        exhausted_at=row.exhausted_at,
    )


def _locked_row(db: Session, principal: str, day: date) -> UsageBudget:
    db.execute(
        insert(UsageBudget)
        .values(
            principal=principal,
            day=day,
            turns=0,
            prompt_tokens=0,
            completion_tokens=0,
            tokens=0,
            cost_usd=0.0,
        )
        .on_conflict_do_nothing()
    )
    return db.execute(
        select(UsageBudget)
        .where((UsageBudget.principal == principal) & (UsageBudget.day == day))
        .with_for_update()
    ).scalar_one()


class PostgresBudgetStore(BudgetStore):
    def reserve(self, principal: str, day: date, limits: BudgetLimits) -> Reservation:
        with transaction() as db:
            row = _locked_row(db, principal, day)
            refused = exceeded(_record(row), limits)
            first = False
            if refused:
                first = row.exhausted_at is None
                if first:
                    row.exhausted_at = datetime.now(timezone.utc)
            else:
                row.turns += 1
            db.flush()
            return Reservation(record=_record(row), refused=refused, first_refusal=first)

    def charge(self, principal: str, day: date, usage: TokenUsage) -> UsageRecord:
        with transaction() as db:
            row = _locked_row(db, principal, day)
            row.prompt_tokens += usage.prompt_tokens
            row.completion_tokens += usage.completion_tokens
            row.tokens += usage.total_tokens
            row.cost_usd = round(row.cost_usd + usage.cost_usd, 6)
            db.flush()
            return _record(row)

    def get(self, principal: str, day: date) -> UsageRecord:
        with transaction() as db:
            row = db.get(UsageBudget, (principal, day))
            return _record(row) if row else UsageRecord(principal=principal, day=day)

    def list(self, day: date, *, limit: int, offset: int) -> tuple[list[UsageRecord], int]:
        with transaction() as db:
            total = db.scalar(
                select(func.count()).select_from(UsageBudget).where(UsageBudget.day == day)
            )
            rows = db.scalars(
                select(UsageBudget)
                .where(UsageBudget.day == day)
                .order_by(UsageBudget.tokens.desc(), UsageBudget.principal)
                .limit(limit)
                .offset(offset)
            ).all()
            return [_record(r) for r in rows], int(total or 0)

    def purge_before(self, day: date) -> int:
        with transaction() as db:
            result = db.execute(delete(UsageBudget).where(UsageBudget.day < day))
            return int(result.rowcount or 0)  # type: ignore[attr-defined]

    def clear(self) -> None:
        with transaction() as db:
            db.execute(delete(UsageBudget))

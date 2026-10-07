"""Daily usage counters per principal (memory store; Postgres in ``app.persistence.budgets``)."""

from __future__ import annotations

import threading
from datetime import date, datetime, timezone
from functools import lru_cache

from pydantic import BaseModel

from app.config import get_settings
from app.policies.config import BudgetLimits
from app.quotas.usage import TokenUsage


class UsageRecord(BaseModel):
    """One principal's consumption on one UTC day."""

    principal: str
    day: date
    turns: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tokens: int = 0  # total, including estimates for turns no LLM counted
    cost_usd: float = 0.0
    exhausted_at: datetime | None = None  # first refusal of the day


def exceeded(record: UsageRecord, limits: BudgetLimits) -> str | None:
    """The first limit ``record`` has used up (``turns``/``tokens``/``cost``), if any."""
    if limits.daily_turns and record.turns >= limits.daily_turns:
        return "turns"
    if limits.daily_tokens and record.tokens >= limits.daily_tokens:
        return "tokens"
    if limits.daily_cost_usd and record.cost_usd >= limits.daily_cost_usd:
        return "cost"
    return None


class Reservation(BaseModel):
    record: UsageRecord
    refused: str | None = None  # the limit that refused the turn
    first_refusal: bool = False  # the first refusal today (worth an audit event)


class BudgetStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, date], UsageRecord] = {}
        self._lock = threading.Lock()

    def _row(self, principal: str, day: date) -> UsageRecord:
        key = (principal, day)
        if key not in self._rows:
            self._rows[key] = UsageRecord(principal=principal, day=day)
        return self._rows[key]

    def reserve(self, principal: str, day: date, limits: BudgetLimits) -> Reservation:
        """Count a turn if every limit has room left — atomically."""
        with self._lock:
            row = self._row(principal, day)
            refused = exceeded(row, limits)
            first = False
            if refused:
                first = row.exhausted_at is None
                if first:
                    row.exhausted_at = datetime.now(timezone.utc)
            else:
                row.turns += 1
            return Reservation(record=row.model_copy(), refused=refused, first_refusal=first)

    def charge(self, principal: str, day: date, usage: TokenUsage) -> UsageRecord:
        with self._lock:
            row = self._row(principal, day)
            row.prompt_tokens += usage.prompt_tokens
            row.completion_tokens += usage.completion_tokens
            row.tokens += usage.total_tokens
            row.cost_usd = round(row.cost_usd + usage.cost_usd, 6)
            return row.model_copy()

    def get(self, principal: str, day: date) -> UsageRecord:
        with self._lock:
            row = self._rows.get((principal, day))
            return row.model_copy() if row else UsageRecord(principal=principal, day=day)

    def list(self, day: date, *, limit: int, offset: int) -> tuple[list[UsageRecord], int]:
        """``day``'s records, heaviest token users first, and how many there are."""
        with self._lock:
            rows = [r.model_copy() for (_, d), r in self._rows.items() if d == day]
        rows.sort(key=lambda r: (-r.tokens, r.principal))
        return rows[offset : offset + limit], len(rows)

    def purge_before(self, day: date) -> int:
        with self._lock:
            old = [k for k in self._rows if k[1] < day]
            for key in old:
                del self._rows[key]
            return len(old)

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()


@lru_cache
def get_budget_store() -> BudgetStore:
    if get_settings().use_postgres:
        from app.persistence.budgets import PostgresBudgetStore

        return PostgresBudgetStore()
    return BudgetStore()

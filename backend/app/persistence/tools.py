"""Tool gateway with a durable request log (``tool_requests``) and shared rate limits."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select

from app.database.models import ToolRequest
from app.database.sync import transaction
from app.persistence.ratelimit import PostgresRateLimiter
from app.tools.gateway import ToolGateway
from app.tools.schemas import CheckResult, ToolCallResult


def _to_result(row: ToolRequest) -> ToolCallResult:
    return ToolCallResult(
        id=str(row.id),
        agent=row.agent,
        session_id=row.session_id,
        tool=row.tool,
        arguments=row.arguments or {},
        status=row.status,
        decision_reason=row.decision_reason or "",
        checks=[CheckResult.model_validate(c) for c in row.checks or []],
        output=row.output,
        output_action=row.output_action,
        redactions=row.redactions or {},
        requested_at=row.requested_at,
        decided_at=row.decided_at,
    )


class PostgresToolGateway(ToolGateway):
    def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(**kwargs)
        self._limiter = PostgresRateLimiter()

    def _store_request(self, result: ToolCallResult) -> None:
        with transaction() as db:
            db.add(
                ToolRequest(
                    id=uuid.UUID(result.id),
                    agent=result.agent,
                    session_id=result.session_id,
                    tool=result.tool,
                    arguments=result.arguments,
                    status=result.status,
                    decision_reason=result.decision_reason,
                    checks=[c.model_dump(mode="json") for c in result.checks],
                    output=result.output,
                    output_action=result.output_action.value if result.output_action else None,
                    redactions=result.redactions,
                    requested_at=result.requested_at,
                    decided_at=result.decided_at,
                )
            )

    def requests(self, *, agent: str | None = None, limit: int = 100) -> list[ToolCallResult]:
        query = select(ToolRequest).order_by(ToolRequest.requested_at.desc()).limit(limit)
        if agent is not None:
            query = query.where(func.lower(ToolRequest.agent) == agent.lower())
        with transaction() as db:
            return [_to_result(row) for row in db.scalars(query)]

    def _take_rate_slot(self, agent: str, tool: str, limit: int) -> bool:
        key = f"tool:{agent.lower()}:{tool}"
        return self._limiter.try_acquire(key, limit=limit, window_seconds=60) == 0

    def clear(self) -> None:
        with transaction() as db:
            db.execute(delete(ToolRequest))
        self._limiter.clear("tool:")

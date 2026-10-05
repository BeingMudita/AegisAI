"""Tool gateway with a durable request log (``tool_requests``) and shared rate limits.

Approval claims are a single ``UPDATE … WHERE status = 'PENDING' RETURNING``, so
a request can be decided exactly once even with several admins and workers.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.database.enums import ToolRequestStatus
from app.database.models import ToolRequest
from app.database.sync import transaction
from app.persistence.ratelimit import PostgresRateLimiter
from app.tools.gateway import ApprovalError, ToolGateway
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
        expires_at=row.expires_at,
        reviewed_by=row.reviewed_by,
        review_note=row.review_note,
        reviewed_at=row.reviewed_at,
    )


def _values(result: ToolCallResult) -> dict:
    return {
        "agent": result.agent,
        "session_id": result.session_id,
        "tool": result.tool,
        "arguments": result.arguments,
        "status": result.status,
        "decision_reason": result.decision_reason,
        "checks": [c.model_dump(mode="json") for c in result.checks],
        "output": result.output,
        "output_action": result.output_action.value if result.output_action else None,
        "redactions": result.redactions,
        "requested_at": result.requested_at,
        "decided_at": result.decided_at,
        "expires_at": result.expires_at,
        "reviewed_by": result.reviewed_by,
        "review_note": result.review_note,
        "reviewed_at": result.reviewed_at,
    }


class PostgresToolGateway(ToolGateway):
    def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(**kwargs)
        self._limiter = PostgresRateLimiter()

    def _save_request(self, result: ToolCallResult) -> None:
        values = _values(result)
        stmt = insert(ToolRequest).values(id=uuid.UUID(result.id), **values)
        stmt = stmt.on_conflict_do_update(index_elements=[ToolRequest.id], set_=values)
        with transaction() as db:
            db.execute(stmt)

    def requests(self, *, agent: str | None = None, limit: int = 100) -> list[ToolCallResult]:
        query = select(ToolRequest).order_by(ToolRequest.requested_at.desc()).limit(limit)
        if agent is not None:
            query = query.where(func.lower(ToolRequest.agent) == agent.lower())
        with transaction() as db:
            return [_to_result(row) for row in db.scalars(query)]

    def _pending_requests(self) -> list[ToolCallResult]:
        query = (
            select(ToolRequest)
            .where(ToolRequest.status == ToolRequestStatus.PENDING)
            .order_by(ToolRequest.requested_at.desc())
        )
        with transaction() as db:
            return [_to_result(row) for row in db.scalars(query)]

    def _claim(self, request_id: str, reviewer: str, note: str) -> ToolCallResult:
        try:
            rid = uuid.UUID(request_id)
        except ValueError as exc:
            raise ApprovalError("Approval request not found.", not_found=True) from exc
        with transaction() as db:
            row = db.scalars(
                update(ToolRequest)
                .where((ToolRequest.id == rid) & (ToolRequest.status == ToolRequestStatus.PENDING))
                .values(
                    status=ToolRequestStatus.APPROVED,
                    reviewed_by=reviewer,
                    review_note=note or None,
                    reviewed_at=datetime.now(timezone.utc),
                )
                .returning(ToolRequest)
            ).first()
            if row is not None:
                return _to_result(row)
            existing = db.get(ToolRequest, rid)
        if existing is None:
            raise ApprovalError("Approval request not found.", not_found=True)
        raise ApprovalError(f"Request is already {existing.status.value.lower()}.")

    def _take_rate_slot(self, agent: str, tool: str, limit: int) -> bool:
        key = f"tool:{agent.lower()}:{tool}"
        return self._limiter.try_acquire(key, limit=limit, window_seconds=60) == 0

    def clear(self) -> None:
        with transaction() as db:
            db.execute(delete(ToolRequest))
        self._limiter.clear("tool:")

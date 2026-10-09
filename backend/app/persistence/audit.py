"""Durable audit log: ``security_events`` and ``decision_counters``.

Security events are written as they happen. Decision counters change on every
checkpoint (several per agent turn), and all workers would contend for the same few
counter rows, so each worker adds its counts up in memory and writes them in one
statement at most every ``FLUSH_INTERVAL`` seconds — and before it reports a summary,
and at shutdown. A crash can lose at most that interval's worth of counts.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Row, delete, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert

from app.database.enums import SecurityEventType, SecuritySeverity
from app.database.models import DecisionCounter, SecurityEvent
from app.database.sync import transaction
from app.telemetry.schemas import DecisionCount, SecurityEventRecord, TelemetrySummary
from app.telemetry.store import AuditLog


class AuditClearForbidden(RuntimeError):
    """The durable audit log is not erasable through the application."""


def _to_record(row: SecurityEvent) -> SecurityEventRecord:
    return SecurityEventRecord(
        id=str(row.id),
        event_type=row.event_type,
        severity=row.severity,
        agent=row.actor,
        session_id=row.session_id,
        source=row.source or "",
        description=row.description or "",
        details=row.details or {},
        created_at=row.created_at,
    )


FLUSH_INTERVAL = 2.0  # seconds


class PostgresAuditLog(AuditLog):
    def __init__(self) -> None:
        super().__init__(max_events=1)  # the in-memory buffer is unused
        self._pending: dict[str, Counter[str]] = {}
        self._pending_lock = threading.Lock()
        self._last_flush = time.monotonic()

    # ------------------------------------------------------------- writing
    def _store_event(self, event: SecurityEventRecord) -> None:
        with transaction() as db:
            db.add(
                SecurityEvent(
                    id=uuid.UUID(event.id),
                    event_type=event.event_type,
                    severity=event.severity,
                    actor=event.agent,
                    session_id=event.session_id,
                    source=event.source,
                    description=event.description,
                    details=event.details,
                    created_at=event.created_at,
                )
            )

    def count_decisions(self, component: str, *, allowed: int = 0, denied: int = 0) -> None:
        if not allowed and not denied:
            return
        with self._pending_lock:
            counter = self._pending.setdefault(component, Counter())
            counter["allowed"] += allowed
            counter["denied"] += denied
            due = time.monotonic() - self._last_flush >= FLUSH_INTERVAL
        if due:
            self.flush()

    def flush(self) -> None:
        """Write the buffered decision counts (one upsert for every component)."""
        with self._pending_lock:
            pending, self._pending = self._pending, {}
            self._last_flush = time.monotonic()
        if not pending:
            return
        rows = [
            {"component": c, "allowed": n["allowed"], "denied": n["denied"]}
            for c, n in sorted(pending.items())
        ]
        stmt = insert(DecisionCounter).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[DecisionCounter.component],
            set_={
                "allowed": DecisionCounter.allowed + stmt.excluded.allowed,
                "denied": DecisionCounter.denied + stmt.excluded.denied,
            },
        )
        try:
            with transaction() as db:
                db.execute(stmt)
        except Exception:
            with self._pending_lock:  # keep the counts for the next attempt
                for component, counts in pending.items():
                    self._pending.setdefault(component, Counter()).update(counts)
            raise

    # ------------------------------------------------------------- reading
    def list_events(
        self,
        *,
        event_type: SecurityEventType | None = None,
        severity: SecuritySeverity | None = None,
        agent: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
        before: tuple[datetime, str] | None = None,
    ) -> list[SecurityEventRecord]:
        query = select(SecurityEvent)
        if before is not None:
            stamp, event_id = before
            try:
                key = uuid.UUID(event_id)
            except ValueError:
                return []
            query = query.where(tuple_(SecurityEvent.created_at, SecurityEvent.id) < (stamp, key))
        if event_type is not None:
            query = query.where(SecurityEvent.event_type == event_type)
        if severity is not None:
            query = query.where(SecurityEvent.severity == severity)
        if agent is not None:
            query = query.where(func.lower(SecurityEvent.actor) == agent.lower())
        if session_id is not None:
            query = query.where(SecurityEvent.session_id == session_id)
        query = query.order_by(SecurityEvent.created_at.desc(), SecurityEvent.id.desc()).limit(
            limit
        )
        with transaction() as db:
            return [_to_record(row) for row in db.scalars(query)]

    def summary(self) -> TelemetrySummary:
        self.flush()
        with transaction() as db:
            total = db.scalar(select(func.count()).select_from(SecurityEvent)) or 0

            def grouped(column: Any) -> Sequence[Row[Any]]:
                return db.execute(select(column, func.count()).group_by(column)).all()

            by_type = {k.value: n for k, n in grouped(SecurityEvent.event_type)}
            by_severity = {k.value: n for k, n in grouped(SecurityEvent.severity)}
            by_agent = {(k or "unknown"): n for k, n in grouped(SecurityEvent.actor)}
            counters = db.scalars(select(DecisionCounter).order_by(DecisionCounter.component)).all()
            decisions = [
                DecisionCount(component=c.component, allowed=c.allowed, denied=c.denied)
                for c in counters
            ]
        return TelemetrySummary(
            total_events=total,
            by_type=by_type,
            by_severity=by_severity,
            by_agent=by_agent,
            decisions=decisions,
        )

    def purge_before(self, cutoff: datetime) -> int:
        """Retention: delete events recorded before ``cutoff`` — the only way events
        leave the durable log."""
        with transaction() as db:
            result = db.execute(delete(SecurityEvent).where(SecurityEvent.created_at < cutoff))
            return int(result.rowcount or 0)  # type: ignore[attr-defined]

    def clear(self) -> None:
        raise AuditClearForbidden(
            "The durable audit log can't be cleared through the application; "
            "it is pruned by the retention policy."
        )

    def truncate_for_tests(self) -> None:
        """Test-suite helper: wipe events and counters."""
        with self._pending_lock:
            self._pending.clear()
        with transaction() as db:
            db.execute(delete(SecurityEvent))
            db.execute(delete(DecisionCounter))

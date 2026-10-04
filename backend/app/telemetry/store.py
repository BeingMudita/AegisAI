"""Audit log — records every checkpoint decision and security event.

:class:`AuditLog` keeps events in a bounded in-memory buffer (newest last) and
mirrors them to structured logs. With ``STORAGE_BACKEND=postgres`` the
``security_events`` and ``decision_counters`` tables are the durable sink instead
(:class:`app.persistence.audit.PostgresAuditLog`); callers only ever talk to the
``AuditLog`` interface, so they don't change.
"""

from __future__ import annotations

import threading
from collections import Counter, deque
from functools import lru_cache
from typing import Any

import structlog

from app.config import get_settings
from app.database.enums import SecurityEventType, SecuritySeverity
from app.telemetry.schemas import DecisionCount, SecurityEventRecord, TelemetrySummary

logger = structlog.get_logger("aegisai.audit")


class AuditLog:
    """Thread-safe, bounded store of security events and decision counters."""

    def __init__(self, max_events: int = 5000) -> None:
        self._events: deque[SecurityEventRecord] = deque(maxlen=max_events)
        self._decisions: dict[str, Counter[str]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------- writing
    def record_event(
        self,
        *,
        event_type: SecurityEventType,
        severity: SecuritySeverity,
        source: str,
        description: str,
        agent: str | None = None,
        session_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> SecurityEventRecord:
        """Store a security event and emit it as a structured log line."""
        event = SecurityEventRecord(
            event_type=event_type,
            severity=severity,
            source=source,
            description=description,
            agent=agent,
            session_id=session_id,
            details=details or {},
        )
        self._store_event(event)
        logger.warning(
            "security_event",
            event_type=event_type.value,
            severity=severity.value,
            source=source,
            agent=agent,
            description=description,
        )
        return event

    def log_decision(
        self,
        component: str,
        *,
        allowed: bool,
        subject: str | None = None,
        agent: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Count (and log) a single allow/deny decision made by ``component``."""
        self.count_decisions(component, allowed=int(allowed), denied=int(not allowed))
        logger.info(
            "decision",
            component=component,
            allowed=allowed,
            subject=subject,
            agent=agent,
            reason=reason,
        )

    def _store_event(self, event: SecurityEventRecord) -> None:
        with self._lock:
            self._events.append(event)

    def count_decisions(self, component: str, *, allowed: int = 0, denied: int = 0) -> None:
        """Add many decisions at once (bulk ingestion) without per-item log lines."""
        if not allowed and not denied:
            return
        with self._lock:
            counter = self._decisions.setdefault(component, Counter())
            counter["allowed"] += allowed
            counter["denied"] += denied

    # ------------------------------------------------------------- reading
    def list_events(
        self,
        *,
        event_type: SecurityEventType | None = None,
        severity: SecuritySeverity | None = None,
        agent: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[SecurityEventRecord]:
        """Return matching events, newest first."""
        with self._lock:
            events = list(self._events)
        out: list[SecurityEventRecord] = []
        for event in reversed(events):
            if event_type is not None and event.event_type != event_type:
                continue
            if severity is not None and event.severity != severity:
                continue
            if agent is not None and (event.agent or "").lower() != agent.lower():
                continue
            if session_id is not None and event.session_id != session_id:
                continue
            out.append(event)
            if len(out) >= limit:
                break
        return out

    def summary(self) -> TelemetrySummary:
        """Aggregate counts for dashboards."""
        with self._lock:
            events = list(self._events)
            decisions = {k: Counter(v) for k, v in self._decisions.items()}
        return TelemetrySummary(
            total_events=len(events),
            by_type=dict(Counter(e.event_type.value for e in events)),
            by_severity=dict(Counter(e.severity.value for e in events)),
            by_agent=dict(Counter(e.agent or "unknown" for e in events)),
            decisions=[
                DecisionCount(component=c, allowed=v["allowed"], denied=v["denied"])
                for c, v in sorted(decisions.items())
            ],
        )

    def clear(self) -> None:
        """Drop all events and counters (tests / admin reset)."""
        with self._lock:
            self._events.clear()
            self._decisions.clear()


@lru_cache
def get_audit_log() -> AuditLog:
    """Return the process-wide audit log (durable in Postgres mode)."""
    settings = get_settings()
    if settings.use_postgres:
        from app.persistence.audit import PostgresAuditLog

        return PostgresAuditLog()
    return AuditLog(max_events=settings.audit_buffer_size)

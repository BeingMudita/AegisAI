"""Retention: expire idle sessions and delete data older than its retention period.

=================  =========================  ==========================
What               Setting (0 = keep forever)  Removed
=================  =========================  ==========================
Idle sessions      SESSION_IDLE_MINUTES       marked EXPIRED
Ended sessions     SESSION_RETENTION_DAYS     deleted with turns and runs
Security events    AUDIT_RETENTION_DAYS       deleted
Budget counters    USAGE_RETENTION_DAYS       deleted
=================  =========================  ==========================

Retention is the only way events leave the durable audit log. A background
sweeper runs it every RETENTION_INTERVAL_MINUTES; with several API workers on
PostgreSQL an advisory lock makes sure only one of them sweeps at a time.
``aegis retention`` runs it once by hand.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import structlog
from pydantic import BaseModel
from sqlalchemy import text

from app.agents.sessions import get_session_store, idle_cutoff
from app.config import get_settings
from app.quotas.store import get_budget_store
from app.telemetry.store import _process_audit_log

logger = structlog.get_logger("aegisai.retention")

_LOCK_KEY = 0x4145_4749_5352_4554  # "AEGISRET": one sweeper across workers


class RetentionReport(BaseModel):
    ran_at: datetime
    expired_sessions: int = 0
    purged_sessions: int = 0
    purged_events: int = 0
    purged_usage_rows: int = 0
    skipped: bool = False  # another worker held the sweep lock


def _days_ago(now: datetime, days: int) -> datetime | None:
    return now - timedelta(days=days) if days > 0 else None


def _sweep(now: datetime) -> RetentionReport:
    settings = get_settings()
    report = RetentionReport(ran_at=now)
    sessions = get_session_store()
    if (cutoff := idle_cutoff(now)) is not None:
        report.expired_sessions = sessions.expire_idle(cutoff)
    if (cutoff := _days_ago(now, settings.session_retention_days)) is not None:
        report.purged_sessions = sessions.purge_ended_before(cutoff)
    if (cutoff := _days_ago(now, settings.audit_retention_days)) is not None:
        # The process log, never a red-team run's private one.
        report.purged_events = _process_audit_log().purge_before(cutoff)
    if (cutoff := _days_ago(now, settings.usage_retention_days)) is not None:
        report.purged_usage_rows = get_budget_store().purge_before(cutoff.date())
    return report


def run_retention(now: datetime | None = None) -> RetentionReport:
    """Run one retention pass (on PostgreSQL, only if no other worker is running one)."""
    now = now or datetime.now(timezone.utc)
    if not get_settings().use_postgres:
        report = _sweep(now)
    else:
        from app.database.sync import get_sync_engine

        with get_sync_engine().connect() as conn:
            locked = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY})
            if not locked.scalar():
                return RetentionReport(ran_at=now, skipped=True)
            try:
                report = _sweep(now)
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
                conn.commit()
    logger.info("retention", **report.model_dump(mode="json"))
    return report


class RetentionSweeper:
    """Runs :func:`run_retention` in a daemon thread every ``interval`` seconds."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                run_retention()
            except Exception as exc:  # keep sweeping; the next pass may succeed
                logger.warning("retention_failed", error=f"{type(exc).__name__}: {exc}")

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="aegis-retention", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

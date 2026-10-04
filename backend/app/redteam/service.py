"""Red-team runs started from the dashboard.

A run executes in a background thread with its own audit log (see
:func:`app.telemetry.store.isolated_audit_log`) and fresh trust, gateway and
knowledge-base instances, so the simulated attacks never touch live state or the
real audit trail. Only one run may execute at a time.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Protocol

import structlog

from app.config import get_settings
from app.redteam.runner import (
    load_agent_scenarios,
    load_firewall_cases,
    run_agent_scenarios,
    run_firewall_benchmark,
)
from app.redteam.schemas import RedTeamRun, RunSummary, Suite
from app.telemetry.store import isolated_audit_log

logger = structlog.get_logger("aegisai.redteam")
_HISTORY = 25
PROGRESS_SAVE_INTERVAL = 0.25  # seconds between progress writes during a run
STALE_AFTER = timedelta(minutes=15)  # a "running" run older than this died with its worker


class RunConflict(RuntimeError):
    """Another red-team run is still executing."""


class RunStore(Protocol):
    def save(self, run: RedTeamRun) -> None: ...

    def get(self, run_id: str) -> RedTeamRun | None: ...

    def recent(self, limit: int) -> list[RedTeamRun]: ...

    def clear(self) -> None: ...


class MemoryRunStore:
    def __init__(self) -> None:
        self._runs: OrderedDict[str, RedTeamRun] = OrderedDict()
        self._lock = threading.Lock()

    def save(self, run: RedTeamRun) -> None:
        with self._lock:
            self._runs[run.id] = run.model_copy(deep=True)
            while len(self._runs) > _HISTORY:
                self._runs.popitem(last=False)

    def get(self, run_id: str) -> RedTeamRun | None:
        with self._lock:
            run = self._runs.get(run_id)
            return run.model_copy(deep=True) if run else None

    def recent(self, limit: int) -> list[RedTeamRun]:
        with self._lock:
            return [r.model_copy(deep=True) for r in reversed(self._runs.values())][:limit]

    def clear(self) -> None:
        with self._lock:
            self._runs.clear()


class RedTeamService:
    def __init__(self, store: RunStore) -> None:
        self.store = store
        self._lock = threading.Lock()

    def _running(self) -> RedTeamRun | None:
        cutoff = datetime.now(timezone.utc) - STALE_AFTER
        return next(
            (
                r
                for r in self.store.recent(_HISTORY)
                if r.status == "running" and r.started_at > cutoff
            ),
            None,
        )

    def start(self, suites: list[Suite], started_by: str, *, wait: bool = False) -> RedTeamRun:
        with self._lock:
            if self._running() is not None:
                raise RunConflict("A red-team run is already in progress.")
            ordered = [s for s in ("firewall", "agents") if s in suites]
            total = (len(load_firewall_cases()) if "firewall" in ordered else 0) + (
                len(load_agent_scenarios()) if "agents" in ordered else 0
            )
            run = RedTeamRun(suites=ordered, started_by=started_by, progress_total=total)
            self.store.save(run)
        thread = threading.Thread(
            target=self._execute, args=(run,), daemon=True, name="aegis-redteam"
        )
        thread.start()
        if wait:
            thread.join()
            return self.store.get(run.id) or run
        return run

    def _execute(self, run: RedTeamRun) -> None:
        last_save = [0.0]

        def tick() -> None:
            run.progress_done += 1
            now = time.monotonic()
            if now - last_save[0] >= PROGRESS_SAVE_INTERVAL:  # throttle progress writes
                last_save[0] = now
                self.store.save(run)

        try:
            with isolated_audit_log():  # simulated attacks stay out of the real audit trail
                if "firewall" in run.suites:
                    run.firewall = run_firewall_benchmark(progress=tick)
                    self.store.save(run)
                if "agents" in run.suites:
                    run.agents = run_agent_scenarios(progress=tick)
            run.status = "completed"
        except Exception as exc:  # noqa: BLE001 — report any failure on the run itself
            logger.warning("redteam_run_failed", run=run.id, error=str(exc))
            run.status = "failed"
            run.error = str(exc)
        finally:
            run.finished_at = datetime.now(timezone.utc)
            self.store.save(run)

    def get(self, run_id: str) -> RedTeamRun | None:
        return self.store.get(run_id)

    def history(self, limit: int = 20) -> list[RunSummary]:
        return [RunSummary.of(r) for r in self.store.recent(limit)]

    def latest_completed(self) -> RedTeamRun | None:
        return next((r for r in self.store.recent(_HISTORY) if r.status == "completed"), None)


@lru_cache
def get_redteam_service() -> RedTeamService:
    if get_settings().use_postgres:
        from app.persistence.redteam import PostgresRunStore

        return RedTeamService(PostgresRunStore())
    return RedTeamService(MemoryRunStore())

"""Session store — conversations between principals and agents.

:class:`SessionStore` keeps sessions in memory (one API worker). With
``STORAGE_BACKEND=postgres``, :class:`app.persistence.sessions.PostgresSessionStore`
keeps them in ``agent_sessions`` / ``session_runs`` / ``agent_turns`` so locks,
progress and replay rejection hold across workers. Callers only use this interface.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from functools import lru_cache

from app.agents.schemas import (
    AgentSessionRecord,
    AgentTurn,
    RunProgress,
    SessionSummary,
    TraceEntry,
)
from app.config import get_settings
from app.database.enums import SessionStatus


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, AgentSessionRecord] = {}
        self._lock = threading.Lock()
        self._progress: dict[str, RunProgress] = {}
        self._request_ids: dict[str, set[str]] = {}

    def begin_turn(self, session_id: str, request_id: str) -> None:
        with self._lock:
            session = self._sessions[session_id]
            if session.status != SessionStatus.ACTIVE:
                raise ValueError("Session is closed.")
            previous = self._progress.get(session_id)
            if previous and previous.status == "running":
                raise ValueError("A turn is already running in this session.")
            # Do not silently execute a retried request twice.
            seen = self._request_ids.setdefault(session_id, set())
            if request_id in seen:
                raise ValueError("Request already attempted. Review the session before retrying.")
            seen.add(request_id)
            self._progress[session_id] = RunProgress(request_id=request_id)

    def report_progress(self, session_id: str, entry: TraceEntry) -> None:
        with self._lock:
            progress = self._progress[session_id]
            progress.current_stage = entry.stage
            progress.stages = [s for s in progress.stages if s.stage != entry.stage] + [entry]

    def finish_turn(self, session_id: str, turn: AgentTurn | None) -> None:
        with self._lock:
            progress = self._progress[session_id]
            if turn:
                self._sessions[session_id].turns.append(turn)
            progress.status = (
                "failed" if turn is None else "blocked" if turn.blocked else "completed"
            )
            if turn is None:
                for entry in progress.stages:
                    if entry.status == "running":
                        entry.status = "failed"
            progress.finished_at = datetime.now(timezone.utc)
            progress.current_stage = None

    def progress(self, session_id: str) -> RunProgress | None:
        with self._lock:
            progress = self._progress.get(session_id)
            return progress.model_copy(deep=True) if progress else None

    def create(self, agent: str, owner: str) -> AgentSessionRecord:
        session = AgentSessionRecord(agent=agent, owner=owner)
        with self._lock:
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> AgentSessionRecord | None:
        with self._lock:
            return self._sessions.get(session_id)

    def list(self, owner: str | None = None) -> list[SessionSummary]:
        with self._lock:
            sessions = list(self._sessions.values())
        return [
            SessionSummary(
                id=s.id,
                agent=s.agent,
                owner=s.owner,
                status=s.status,
                created_at=s.created_at,
                ended_at=s.ended_at,
                turns=len(s.turns),
                blocked_turns=sum(t.blocked for t in s.turns),
            )
            for s in sorted(sessions, key=lambda s: s.created_at, reverse=True)
            if owner is None or s.owner == owner
        ]

    def add_turn(self, session_id: str, turn: AgentTurn) -> None:
        with self._lock:
            self._sessions[session_id].turns.append(turn)

    def close(
        self, session_id: str, status: SessionStatus = SessionStatus.CLOSED
    ) -> AgentSessionRecord | None:
        with self._lock:
            session = self._sessions.get(session_id)
            progress = self._progress.get(session_id)
            if progress and progress.status == "running":
                raise ValueError("Wait for the running turn before closing this session.")
            if session and session.status == SessionStatus.ACTIVE:
                session.status = status
                session.ended_at = datetime.now(timezone.utc)
            return session

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._progress.clear()
            self._request_ids.clear()


@lru_cache
def get_session_store() -> SessionStore:
    """The process-wide session store (shared across workers in Postgres mode)."""
    if get_settings().use_postgres:
        from app.persistence.sessions import PostgresSessionStore

        return PostgresSessionStore()
    return SessionStore()

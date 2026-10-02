"""Session store — conversations between principals and agents.

In-memory interim store (mirrors the ``agent_sessions`` table), like the
other stores; :class:`SessionStore` is the only interface callers use.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from functools import lru_cache

from app.agents.schemas import AgentSessionRecord, AgentTurn, SessionSummary
from app.database.enums import SessionStatus


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, AgentSessionRecord] = {}
        self._lock = threading.Lock()

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
            if session and session.status == SessionStatus.ACTIVE:
                session.status = status
                session.ended_at = datetime.now(timezone.utc)
            return session

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()


@lru_cache
def get_session_store() -> SessionStore:
    return SessionStore()

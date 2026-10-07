"""Proxy session tracking.

The proxy is otherwise stateless, but correlating the events of one agent turn
(input → tool calls → output) under a ``session_id`` makes the audit trail and
the trust signals coherent. This is a small, bounded, in-memory registry; the
authoritative security state still lives in the trust engine and audit log.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from app.platform.protocol.schemas import Decision


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SessionState(BaseModel):
    session_id: str
    agent: str
    created_at: datetime = Field(default_factory=_now)
    last_seen: datetime = Field(default_factory=_now)
    events: int = 0
    blocked: int = 0


class SessionRegistry:
    """A bounded LRU of recent proxy sessions."""

    def __init__(self, max_sessions: int = 1000) -> None:
        self._sessions: OrderedDict[str, SessionState] = OrderedDict()
        self._max = max_sessions
        self._lock = threading.Lock()

    def touch(self, agent: str, session_id: str | None) -> SessionState:
        """Return (creating if needed) the state for a session."""
        sid = session_id or f"proxy-{uuid4().hex[:12]}"
        with self._lock:
            state = self._sessions.get(sid)
            if state is None:
                state = SessionState(session_id=sid, agent=agent)
                self._sessions[sid] = state
                while len(self._sessions) > self._max:
                    self._sessions.popitem(last=False)
            else:
                state.last_seen = _now()
                self._sessions.move_to_end(sid)
            return state

    def record(self, session_id: str, decision: Decision) -> None:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                return
            state.events += 1
            if decision == Decision.BLOCK:
                state.blocked += 1
            state.last_seen = _now()

    def get(self, session_id: str) -> SessionState | None:
        with self._lock:
            return self._sessions.get(session_id)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()


_registry = SessionRegistry()


def get_session_registry() -> SessionRegistry:
    """Return the process-wide proxy session registry."""
    return _registry

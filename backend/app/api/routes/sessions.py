"""Sessions routes — agent conversation lifecycle.

Any authenticated principal may open a session with an agent and send it
messages; each message runs one guarded agent turn, with trust scoped to the
principal who sent it. Staff can see every session, other roles only their own.

Handlers are plain ``def`` so FastAPI runs them in a worker thread: the session
store may block on the database.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.agents.runtime import get_runtime
from app.agents.schemas import (
    AgentSessionRecord,
    AgentTurn,
    CreateSessionRequest,
    MessageRequest,
    RunProgress,
)
from app.agents.sessions import get_session_store
from app.api.pagination import decode_cursor, encode_cursor
from app.auth.dependencies import get_current_user
from app.auth.roles import STAFF_ROLES
from app.auth.schemas import User
from app.policies.store import get_policy
from app.quotas.service import get_quota_service

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _owned_session(session_id: str, user: User, *, with_turns: bool = True) -> AgentSessionRecord:
    store = get_session_store()
    session = store.get(session_id) if with_turns else store.head(session_id)
    if session is None or (user.role not in STAFF_ROLES and session.owner != user.username):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return session


@router.get("")
def list_sessions(
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(default=None, description="next_cursor from the previous page"),
    user: User = Depends(get_current_user),
) -> dict:
    """List sessions visible to the caller, newest first, a page at a time."""
    owner = None if user.role in STAFF_ROLES else user.username
    sessions = get_session_store().list(owner, limit=limit + 1, before=decode_cursor(cursor))
    page, more = sessions[:limit], len(sessions) > limit
    return {
        "sessions": [s.model_dump(mode="json") for s in page],
        "requested_by": user.username,
        "next_cursor": encode_cursor(page[-1].created_at, page[-1].id) if more else None,
    }


@router.post("", response_model=AgentSessionRecord, status_code=201)
def create_session(
    body: CreateSessionRequest,
    user: User = Depends(get_current_user),
) -> AgentSessionRecord:
    """Open a session with an agent that has a policy."""
    policy = get_policy(body.agent)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No policy found for agent '{body.agent}'.",
        )
    return get_session_store().create(policy.agent, user.username)


@router.get("/{session_id}", response_model=AgentSessionRecord)
def get_session(session_id: str, user: User = Depends(get_current_user)) -> AgentSessionRecord:
    """A session with its full turn history and security traces."""
    return _owned_session(session_id, user)


@router.post("/{session_id}/messages", response_model=AgentTurn)
def send_message(
    session_id: str,
    body: MessageRequest,
    user: User = Depends(get_current_user),
) -> AgentTurn:
    """Run one agent turn through the full security pipeline.

    Declared sync so FastAPI runs it in a worker thread — the turn may block
    on the LLM.
    """
    session = _owned_session(session_id, user)
    store = get_session_store()
    # Refuse before the request ID is spent, so the caller can retry it tomorrow.
    get_quota_service().check(user.username)
    try:
        store.begin_turn(session.id, str(body.request_id))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    turn = None
    try:
        history = [(t.message, t.answer) for t in session.turns if not t.blocked]
        turn = get_runtime().run_turn(
            agent=session.agent,
            session_id=session.id,
            message=body.message,
            history=history,
            progress=lambda entry: store.report_progress(session.id, entry),
            principal=user.username,
        )
        return turn
    finally:
        store.finish_turn(session.id, turn)


@router.get("/{session_id}/progress", response_model=RunProgress | None)
def run_progress(session_id: str, user: User = Depends(get_current_user)) -> RunProgress | None:
    """Owner/staff-visible progress, using actual graph node boundaries."""
    _owned_session(session_id, user, with_turns=False)  # polled often: skip the turns
    return get_session_store().progress(session_id)


@router.post("/{session_id}/close", response_model=AgentSessionRecord)
def close_session(session_id: str, user: User = Depends(get_current_user)) -> AgentSessionRecord:
    """Close a session; further messages are refused."""
    _owned_session(session_id, user, with_turns=False)
    try:
        closed = get_session_store().close(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    assert closed is not None
    return closed

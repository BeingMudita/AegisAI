"""Sessions routes — agent conversation lifecycle.

Any authenticated principal may open a session with an agent and send it
messages; each message runs one guarded agent turn. Staff can see every
session, other roles only their own.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.agents.runtime import get_runtime
from app.agents.schemas import (
    AgentSessionRecord,
    AgentTurn,
    CreateSessionRequest,
    MessageRequest,
)
from app.agents.sessions import get_session_store
from app.auth.dependencies import get_current_user
from app.auth.roles import STAFF_ROLES
from app.auth.schemas import User
from app.database.enums import SessionStatus
from app.policies.store import get_policy

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _owned_session(session_id: str, user: User) -> AgentSessionRecord:
    session = get_session_store().get(session_id)
    if session is None or (user.role not in STAFF_ROLES and session.owner != user.username):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return session


@router.get("")
async def list_sessions(user: User = Depends(get_current_user)) -> dict:
    """List sessions visible to the caller, newest first."""
    owner = None if user.role in STAFF_ROLES else user.username
    sessions = get_session_store().list(owner)
    return {
        "sessions": [s.model_dump(mode="json") for s in sessions],
        "requested_by": user.username,
    }


@router.post("", response_model=AgentSessionRecord, status_code=201)
async def create_session(
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
async def get_session(
    session_id: str, user: User = Depends(get_current_user)
) -> AgentSessionRecord:
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
    if session.status != SessionStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is closed.")
    history = [(t.message, t.answer) for t in session.turns if not t.blocked]
    turn = get_runtime().run_turn(
        agent=session.agent, session_id=session.id, message=body.message, history=history
    )
    get_session_store().add_turn(session.id, turn)
    return turn


@router.post("/{session_id}/close", response_model=AgentSessionRecord)
async def close_session(
    session_id: str, user: User = Depends(get_current_user)
) -> AgentSessionRecord:
    """Close a session; further messages are refused."""
    _owned_session(session_id, user)
    closed = get_session_store().close(session_id)
    assert closed is not None
    return closed

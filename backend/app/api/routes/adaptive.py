"""Runtime adaptive security routes — observe an agent's posture, lift a quarantine.

The posture (NORMAL → SUSPICIOUS → RESTRICTED → QUARANTINED) is derived from the
agent's live trust score and tightens tool enforcement at the proxy. These
routes surface the current state for the dashboard and let an administrator
reset an agent after review.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user, require_roles
from app.auth.roles import Role
from app.auth.schemas import User
from app.platform.adaptive import AgentStateReport, get_adaptive_monitor

router = APIRouter(prefix="/adaptive", tags=["adaptive"])


@router.get("/agents/{agent_id}", response_model=AgentStateReport)
def agent_state(agent_id: str, user: User = Depends(get_current_user)) -> AgentStateReport:
    """The agent's behavioural state: trust, posture, baseline, recent events."""
    return get_adaptive_monitor().state(agent_id)


@router.post("/agents/{agent_id}/reset", response_model=AgentStateReport)
def reset_agent(agent_id: str, user: User = Depends(require_roles(Role.ADMIN))) -> AgentStateReport:
    """Clear the agent's behavioural baseline (an administrator action)."""
    monitor = get_adaptive_monitor()
    monitor.reset(agent_id)
    return monitor.state(agent_id)

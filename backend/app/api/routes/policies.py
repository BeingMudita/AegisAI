"""Policies routes — view agent policies and query the policy engine.

Read access for staff; write access for ADMIN only. Policies come from the
policy store (see app/policies/store.py): the example JSON files in memory mode,
the ``policies`` table with STORAGE_BACKEND=postgres. Editing policies through the
API is not implemented yet.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_user, require_roles
from app.auth.roles import STAFF_ROLES, Role
from app.auth.schemas import User
from app.policies.engine import PolicyEngine
from app.policies.schemas import AgentAllowances, AgentPolicy, PolicyDecision
from app.policies.store import get_policy, list_policies

router = APIRouter(prefix="/policies", tags=["policies"])


def _engine_for(agent: str) -> PolicyEngine:
    policy = get_policy(agent)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No policy found for agent '{agent}'.",
        )
    return PolicyEngine(policy)


@router.get("", response_model=list[AgentPolicy])
def list_all_policies(
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> list[AgentPolicy]:
    """List all agent policies."""
    return list_policies()


@router.get("/{agent}", response_model=AgentPolicy)
def get_agent_policy(
    agent: str,
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> AgentPolicy:
    """Fetch a single agent's policy."""
    return _engine_for(agent).policy


@router.get("/{agent}/allowances", response_model=AgentAllowances)
def get_allowances(
    agent: str,
    user: User = Depends(get_current_user),
) -> AgentAllowances:
    """Answer 'what is this agent allowed to do?'"""
    return _engine_for(agent).allowances()


@router.get("/{agent}/can-use-tool/{tool}", response_model=PolicyDecision)
def can_use_tool(
    agent: str,
    tool: str,
    user: User = Depends(get_current_user),
) -> PolicyDecision:
    """Decide whether an agent may use a given tool."""
    return _engine_for(agent).can_use_tool(tool)


@router.get("/{agent}/can-access-domain/{domain}", response_model=PolicyDecision)
def can_access_domain(
    agent: str,
    domain: str,
    user: User = Depends(get_current_user),
) -> PolicyDecision:
    """Decide whether an agent may access a given domain."""
    return _engine_for(agent).can_access_domain(domain)


@router.post("", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def create_policy(
    user: User = Depends(require_roles(Role.ADMIN)),
) -> None:
    """Create a policy — not implemented yet (ADMIN only, so the route is reserved)."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Creating policies through the API is not implemented yet.",
    )

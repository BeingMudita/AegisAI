"""Policies routes — view agent policies and query the policy engine.

Read access for staff; write access for ADMIN only. Policies are currently
served from the example store (see app/policies/store.py); PostgreSQL becomes
the source of truth in a later step.
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
async def list_all_policies(
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> list[AgentPolicy]:
    """List all agent policies."""
    return list_policies()


@router.get("/{agent}", response_model=AgentPolicy)
async def get_agent_policy(
    agent: str,
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> AgentPolicy:
    """Fetch a single agent's policy."""
    return _engine_for(agent).policy


@router.get("/{agent}/allowances", response_model=AgentAllowances)
async def get_allowances(
    agent: str,
    user: User = Depends(get_current_user),
) -> AgentAllowances:
    """Answer 'what is this agent allowed to do?'"""
    return _engine_for(agent).allowances()


@router.get("/{agent}/can-use-tool/{tool}", response_model=PolicyDecision)
async def can_use_tool(
    agent: str,
    tool: str,
    user: User = Depends(get_current_user),
) -> PolicyDecision:
    """Decide whether an agent may use a given tool."""
    return _engine_for(agent).can_use_tool(tool)


@router.get("/{agent}/can-access-domain/{domain}", response_model=PolicyDecision)
async def can_access_domain(
    agent: str,
    domain: str,
    user: User = Depends(get_current_user),
) -> PolicyDecision:
    """Decide whether an agent may access a given domain."""
    return _engine_for(agent).can_access_domain(domain)


@router.post("", status_code=201)
async def create_policy(
    user: User = Depends(require_roles(Role.ADMIN)),
) -> dict:
    """Create a policy (placeholder — DB-backed write lands with persistence)."""
    return {"created": False, "detail": "not_implemented"}

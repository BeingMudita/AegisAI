"""Multi-agent orchestration — delegate an action from one agent to another.

Acting as an agent is an operator capability (like ``/api/tools/execute``), so
this is ADMIN-only; on top of that, both agents must belong to the caller's own
tenant, and the orchestrator enforces tenant isolation and the composed policy.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import require_roles
from app.auth.roles import Role
from app.auth.schemas import User
from app.orchestration.orchestrator import get_orchestrator
from app.orchestration.schemas import DelegationRequest, DelegationResult
from app.tenants.store import get_tenant_store

router = APIRouter(prefix="/orchestration", tags=["orchestration"])


@router.post("/delegate", response_model=DelegationResult)
def delegate(
    body: DelegationRequest, user: User = Depends(require_roles(Role.ADMIN))
) -> DelegationResult:
    """``caller`` asks ``callee`` to run a tool. Both must be in the caller's tenant."""
    tenants = get_tenant_store()
    for agent in (body.caller, body.callee):
        if tenants.tenant_of_agent(agent) != user.tenant:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Agent '{agent}' is not in your tenant '{user.tenant}'.",
            )
    return get_orchestrator().delegate(
        caller=body.caller,
        callee=body.callee,
        tool=body.tool,
        arguments=body.arguments,
        session_id=body.session_id,
    )

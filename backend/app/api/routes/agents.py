"""Agents routes — the agents known to AegisAI, their standing and the runtime.

Trust is reported as the caller sees it: the lower of the agent's baseline and
its score with the caller (see :mod:`app.trust.engine`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.agents.brain import get_brain
from app.agents.schemas import AgentInfo
from app.auth.dependencies import get_current_user
from app.auth.schemas import User
from app.policies.store import list_policies
from app.rag.embeddings import get_embedder
from app.tenants.store import get_tenant_store
from app.trust.engine import get_trust_engine
from app.trust.scoring import level_for

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentInfo])
def list_agents(user: User = Depends(get_current_user)) -> list[AgentInfo]:
    """Agents in the caller's tenant, with the trust that gates each for the caller."""
    trust = get_trust_engine()
    tenants = get_tenant_store()
    out = []
    for policy in list_policies():
        if tenants.tenant_of_agent(policy.agent) != user.tenant:
            continue  # tenant isolation: callers see only their own organisation's agents
        score = trust.agent_score(policy.agent, user.username)
        out.append(
            AgentInfo(
                name=policy.agent,
                trust_score=score,
                trust_level=level_for(score).value,
                allowed_tools=policy.allowed_tools,
                blocked_tools=policy.blocked_tools,
                allowed_domains=policy.allowed_domains,
                sensitive_data=policy.sensitive_data,
            )
        )
    return out


@router.get("/runtime")
def runtime_info(user: User = Depends(get_current_user)) -> dict:
    """Which LLM brain and embedder are active."""
    return {"brain": get_brain().name, "embedder": get_embedder().name}

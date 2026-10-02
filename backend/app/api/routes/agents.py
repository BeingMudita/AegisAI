"""Agents routes — the agents known to AegisAI, their standing and the runtime."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.agents.brain import get_brain
from app.agents.schemas import AgentInfo
from app.auth.dependencies import get_current_user
from app.auth.schemas import User
from app.database.enums import SubjectType
from app.policies.store import list_policies
from app.rag.embeddings import get_embedder
from app.trust.engine import get_trust_engine
from app.trust.scoring import level_for

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentInfo])
async def list_agents(user: User = Depends(get_current_user)) -> list[AgentInfo]:
    """Every agent with a policy, with its current trust score."""
    trust = get_trust_engine()
    out = []
    for policy in list_policies():
        score = trust.score(SubjectType.AGENT, policy.agent)
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
async def runtime_info(user: User = Depends(get_current_user)) -> dict:
    """Which LLM brain and embedder are active."""
    return {"brain": get_brain().name, "embedder": get_embedder().name}

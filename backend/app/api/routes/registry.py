"""Agent registry routes — the connect → scan → protect onboarding flow.

Register an agent (framework, tools, data), scan it (discover → audit → generate
policy → red-team), and get back a ready-to-run deployment configuration.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_user
from app.auth.schemas import User
from app.platform.registry import (
    AgentRegistration,
    OnboardingResult,
    RegistryError,
    get_registry,
)

router = APIRouter(prefix="/registry", tags=["registry"])


@router.post("/agents", response_model=AgentRegistration)
def register_agent(
    registration: AgentRegistration, user: User = Depends(get_current_user)
) -> AgentRegistration:
    """Register an agent for onboarding."""
    return get_registry().register(registration)


@router.get("/agents", response_model=list[AgentRegistration])
def list_agents(user: User = Depends(get_current_user)) -> list[AgentRegistration]:
    """List registered agents and their onboarding status."""
    return get_registry().list()


@router.get("/agents/{agent_id}", response_model=AgentRegistration)
def get_agent(agent_id: str, user: User = Depends(get_current_user)) -> AgentRegistration:
    reg = get_registry().get(agent_id)
    if reg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No agent '{agent_id}'.")
    return reg


@router.post("/agents/{agent_id}/scan", response_model=OnboardingResult)
def scan_agent(
    agent_id: str, redteam: bool = True, user: User = Depends(get_current_user)
) -> OnboardingResult:
    """Run the onboarding pipeline for a registered agent.

    Declared sync so FastAPI threadpools it (the red-team step is CPU-bound).
    """
    try:
        return get_registry().onboard(agent_id, redteam=redteam)
    except RegistryError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/agents/{agent_id}/protect")
def protect_agent(agent_id: str, user: User = Depends(get_current_user)) -> dict:
    """Return the deployment configuration for a scanned agent."""
    try:
        return get_registry().protect(agent_id)
    except RegistryError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

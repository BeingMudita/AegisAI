"""Aegis Autopilot routes — runtime-driven policy recommendations.

Autopilot proposes tightening changes from observed behaviour; it never edits a
policy on its own. A human reviews each recommendation and chooses to simulate,
apply or ignore it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import get_current_user, require_roles
from app.auth.roles import Role
from app.auth.schemas import User
from app.platform import autopilot
from app.platform.autopilot import PolicyRecommendation, SimulationResult

router = APIRouter(prefix="/autopilot", tags=["autopilot"])


class RecommendationRef(BaseModel):
    recommendation_id: str


@router.get("/agents/{agent_id}/recommendations", response_model=list[PolicyRecommendation])
def recommendations(
    agent_id: str, user: User = Depends(get_current_user)
) -> list[PolicyRecommendation]:
    """Analyse the agent's runtime behaviour and propose policy changes."""
    try:
        return autopilot.analyze(agent_id)
    except autopilot.AutopilotError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/agents/{agent_id}/simulate", response_model=SimulationResult)
def simulate(
    agent_id: str, body: RecommendationRef, user: User = Depends(get_current_user)
) -> SimulationResult:
    """Score the agent before and after a change, without applying it."""
    try:
        return autopilot.simulate(agent_id, body.recommendation_id)
    except autopilot.AutopilotError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/agents/{agent_id}/apply", response_model=PolicyRecommendation)
def apply(
    agent_id: str, body: RecommendationRef, user: User = Depends(require_roles(Role.ADMIN))
) -> PolicyRecommendation:
    """Apply a recommendation to the live policy (administrator only)."""
    try:
        return autopilot.apply(agent_id, body.recommendation_id)
    except autopilot.AutopilotError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

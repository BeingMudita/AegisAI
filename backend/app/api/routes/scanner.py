"""Scanner routes — the agent security scanner for the operator console.

Profiles a known agent, scores it against the seven risk categories, generates a
least-privilege ``aegis.yaml`` and runs the red-team against it. Mirrors the
``aegis audit`` / ``generate-policy`` / ``policy test`` CLI, for the dashboard.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_user
from app.auth.schemas import User
from app.platform import scanner
from app.redteam.service import RunConflict, get_redteam_service

router = APIRouter(prefix="/scanner", tags=["scanner"])


@router.get("/agents/{agent}/report")
def agent_report(agent: str, user: User = Depends(get_current_user)) -> dict:
    """Full security report for an agent: score, findings, generated policy, OWASP."""
    try:
        return scanner.audit(agent).model_dump()
    except scanner.ScannerError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/agents/{agent}/policy")
def agent_policy(agent: str, user: User = Depends(get_current_user)) -> dict:
    """The least-privilege aegis.yaml generated for an agent."""
    try:
        profile = scanner.profile_known_agent(agent)
    except scanner.ScannerError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"agent": profile.name, "aegis_yaml": scanner.generate_policy(profile).to_yaml()}


@router.post("/agents/{agent}/test")
def agent_policy_test(agent: str, user: User = Depends(get_current_user)) -> dict:
    """Run the red-team agent scenarios against a sandbox and return this agent's results.

    Declared sync so FastAPI runs it in a worker thread (the run is CPU-bound).
    """
    try:
        scanner.profile_known_agent(agent)  # 404 for an unknown agent
    except scanner.ScannerError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    try:
        run = get_redteam_service().start(["agents"], started_by=user.username, wait=True)
    except RunConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if run.status != "completed" or run.agents is None:
        raise HTTPException(status_code=500, detail=run.error or "Red-team run failed.")
    mine = [s.model_dump() for s in run.agents.results if s.agent == agent]
    passed = sum(1 for s in mine if s["passed"])
    return {"agent": agent, "passed": passed, "total": len(mine), "scenarios": mine}

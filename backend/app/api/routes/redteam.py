"""Red-team lab routes: launch the attack suites and read their results.

Staff only. Runs execute in an isolated sandbox runtime; their simulated attacks
never reach the live trust scores, gateway log or audit trail.
"""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import require_roles
from app.auth.roles import STAFF_ROLES
from app.auth.schemas import User
from app.redteam.runner import load_agent_scenarios, load_firewall_cases
from app.redteam.schemas import RedTeamRun, RunRequest, RunSummary
from app.redteam.service import RunConflict, get_redteam_service

router = APIRouter(prefix="/redteam", tags=["red-team"])


@router.get("/suites")
def suites(user: User = Depends(require_roles(*STAFF_ROLES))) -> dict:
    """What a run will execute."""
    cases = load_firewall_cases()
    scenarios = load_agent_scenarios()
    return {
        "firewall": {
            "cases": len(cases),
            "malicious": sum(bool(c["malicious"]) for c in cases),
            "categories": dict(sorted(Counter(c["category"] for c in cases).items())),
        },
        "agents": {
            "scenarios": len(scenarios),
            "items": [{"id": s["id"], "title": s["title"], "agent": s["agent"]} for s in scenarios],
        },
    }


@router.post("/runs", response_model=RedTeamRun, status_code=202)
def start_run(body: RunRequest, user: User = Depends(require_roles(*STAFF_ROLES))) -> RedTeamRun:
    """Start a run in the background; poll it with GET /redteam/runs/{id}."""
    try:
        return get_redteam_service().start(body.suites, user.username)
    except RunConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/runs", response_model=list[RunSummary])
def list_runs(user: User = Depends(require_roles(*STAFF_ROLES))) -> list[RunSummary]:
    """Recent runs, newest first."""
    return get_redteam_service().history()


@router.get("/runs/{run_id}", response_model=RedTeamRun)
def get_run(run_id: str, user: User = Depends(require_roles(*STAFF_ROLES))) -> RedTeamRun:
    run = get_redteam_service().get(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    return run

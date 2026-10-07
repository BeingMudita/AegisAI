"""Attack-surface routes — graph, attack paths, blast radius, risk-guided focus.

Composition-level analysis of an agent's permissions: what its tools, data and
destinations allow when chained, how large its blast radius is if compromised,
and how much least-privilege tightening would shrink it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_user
from app.auth.schemas import User
from app.platform import attackgraph, scanner
from app.platform.attackgraph import AttackSurfaceReport, BlastRadius, HardeningComparison

router = APIRouter(prefix="/attack-surface", tags=["attack-surface"])


def _profile(agent: str):
    try:
        return scanner.profile_known_agent(agent)
    except scanner.ScannerError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/agents/{agent}", response_model=AttackSurfaceReport)
def agent_attack_surface(agent: str, user: User = Depends(get_current_user)) -> AttackSurfaceReport:
    """The full attack-surface report: graph, paths, blast radius, risk focus."""
    return attackgraph.report_for(_profile(agent))


@router.get("/agents/{agent}/blast", response_model=BlastRadius)
def agent_blast_radius(agent: str, user: User = Depends(get_current_user)) -> BlastRadius:
    """The agent's blast radius if it were compromised (0–100, higher = worse)."""
    return attackgraph.blast_radius(_profile(agent))


@router.get("/agents/{agent}/hardening", response_model=HardeningComparison)
def agent_hardening(agent: str, user: User = Depends(get_current_user)) -> HardeningComparison:
    """Blast radius now vs. after least-privilege tightening (the measurable payoff)."""
    return attackgraph.compare_hardening(_profile(agent))

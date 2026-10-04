"""Threat-coverage route: controls mapped to OWASP LLM Top 10 (2025) and MITRE ATLAS."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.auth.schemas import User
from app.compliance.schemas import CoverageReport
from app.compliance.service import coverage_report

router = APIRouter(prefix="/compliance", tags=["compliance"])


@router.get("", response_model=CoverageReport)
def coverage(user: User = Depends(get_current_user)) -> CoverageReport:
    """Every framework threat, its controls, and evidence from the latest red-team run."""
    return coverage_report()

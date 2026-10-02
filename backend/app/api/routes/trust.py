"""Trust routes — inspect and override trust scores for agents, sources, and tools.

Read access for staff (ADMIN, SECURITY_ANALYST); overrides are ADMIN only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import require_roles
from app.auth.roles import STAFF_ROLES, Role
from app.auth.schemas import User
from app.database.enums import SubjectType
from app.trust.engine import get_trust_engine
from app.trust.schemas import TrustAssessmentRecord, TrustOverride, TrustScoreDetail

router = APIRouter(prefix="/trust", tags=["trust"])


@router.get("")
async def list_trust_scores(
    subject_type: SubjectType | None = None,
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict:
    """List current trust scores, lowest first."""
    engine = get_trust_engine()
    scores = engine.list_scores(subject_type)
    return {
        "scores": [s.model_dump(mode="json") for s in scores],
        "threshold": engine.default_threshold,
    }


@router.get("/{subject_type}/{subject_id}", response_model=TrustScoreDetail)
async def get_trust_score(
    subject_type: SubjectType,
    subject_id: str,
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> TrustScoreDetail:
    """A subject's current score and its assessment history (newest first)."""
    detail = get_trust_engine().get(subject_type, subject_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No trust record for {subject_type.value} '{subject_id}'.",
        )
    return detail


@router.put("/{subject_type}/{subject_id}", response_model=TrustAssessmentRecord)
async def override_trust_score(
    subject_type: SubjectType,
    subject_id: str,
    body: TrustOverride,
    user: User = Depends(require_roles(Role.ADMIN)),
) -> TrustAssessmentRecord:
    """Manually set a trust score (e.g. reinstate an agent after review)."""
    return get_trust_engine().override(
        subject_type,
        subject_id,
        body.score,
        rationale=body.rationale,
        assessed_by=user.username,
    )

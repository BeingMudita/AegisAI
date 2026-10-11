"""Trust routes — inspect and override trust scores for agents, sources, and tools.

Read access for staff (ADMIN, SECURITY_ANALYST); overrides are ADMIN only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.dependencies import require_roles
from app.auth.roles import STAFF_ROLES, Role
from app.auth.schemas import User
from app.database.enums import SubjectType, TrustLevel
from app.trust.engine import get_trust_engine
from app.trust.schemas import TrustAssessmentRecord, TrustOverride, TrustScoreDetail

router = APIRouter(prefix="/trust", tags=["trust"])


@router.get("")
def list_trust_scores(
    subject_type: SubjectType | None = None,
    q: str | None = Query(None, max_length=200),
    level: TrustLevel | None = None,
    offset: int = Query(0, ge=0),
    limit: int | None = Query(None, ge=1, le=1000),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict:
    """List current trust scores, lowest first. ``q`` matches the subject name and
    ``level`` the trust level; with ``limit`` only that page is returned (``total``
    counts every match). ``levels`` counts the matches of each level before the level
    filter, so a client can show how many subjects each choice would list."""
    engine = get_trust_engine()
    scores = engine.list_scores(subject_type)
    if q:
        needle = q.casefold()
        scores = [s for s in scores if needle in s.subject_id.casefold()]
    levels = {lv.value: 0 for lv in TrustLevel}
    for s in scores:
        levels[s.level.value] += 1
    if level is not None:
        scores = [s for s in scores if s.level == level]
    page = scores[offset : offset + limit] if limit else scores[offset:]
    return {
        "scores": [s.model_dump(mode="json") for s in page],
        "threshold": engine.default_threshold,
        "total": len(scores),
        "levels": levels,
    }


# ``:path`` because source names are file paths ("corpus/documents/invoice/FIN-….txt").
@router.get("/{subject_type}/{subject_id:path}", response_model=TrustScoreDetail)
def get_trust_score(
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


@router.put("/{subject_type}/{subject_id:path}", response_model=TrustAssessmentRecord)
def override_trust_score(
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

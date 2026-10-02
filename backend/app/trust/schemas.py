"""Pydantic schemas for the trust engine."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.database.enums import SubjectType, TrustLevel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TrustAssessmentRecord(BaseModel):
    """A point-in-time trust change (mirrors ``trust_assessments``)."""

    subject_type: SubjectType
    subject_id: str
    score: float
    previous: float
    level: TrustLevel
    signal: str
    rationale: str | None = None
    assessed_by: str = "trust-engine"
    created_at: datetime = Field(default_factory=_now)


class TrustScore(BaseModel):
    subject_type: SubjectType
    subject_id: str
    score: float
    level: TrustLevel
    updated_at: datetime
    assessments: int


class TrustScoreDetail(TrustScore):
    history: list[TrustAssessmentRecord]


class TrustDecision(BaseModel):
    """Whether a subject's trust clears the bar for an action."""

    allowed: bool
    subject: str
    score: float
    required: float
    level: TrustLevel
    reason: str


class TrustOverride(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    rationale: str = "manual override"

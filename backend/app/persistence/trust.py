"""Durable trust scores: ``trust_scores`` (current) and ``trust_assessments`` (history).

``update`` locks the subject's row (``SELECT … FOR UPDATE``) for the whole
read-modify-write, so concurrent penalties from several workers never overwrite
each other.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.database.enums import SubjectType
from app.database.models import TrustAssessment, TrustScoreRow
from app.database.sync import transaction
from app.trust.engine import HISTORY_LEN, Compute, make_record
from app.trust.schemas import (
    TrustAssessmentRecord,
    TrustScore,
    TrustScoreDetail,
)
from app.trust.scoring import clamp, level_for


def _ensure(db: Session, subject_type: SubjectType, subject_id: str, initial: float) -> None:
    db.execute(
        insert(TrustScoreRow)
        .values(
            subject_type=subject_type,
            subject_key=subject_id.lower(),
            subject_id=subject_id,
            score=initial,
            assessments=0,
            updated_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing()
    )


def _summary(row: TrustScoreRow) -> TrustScore:
    return TrustScore(
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        score=row.score,
        level=level_for(row.score),
        updated_at=row.updated_at,
        assessments=row.assessments,
    )


def _key(subject_type: SubjectType, subject_id: str) -> ColumnElement[bool]:
    return (TrustScoreRow.subject_type == subject_type) & (
        TrustScoreRow.subject_key == subject_id.lower()
    )


class PostgresTrustRepository:
    def get_or_create(self, subject_type: SubjectType, subject_id: str, initial: float) -> float:
        # Every gate reads trust, so the common case (the row exists) stays a plain
        # SELECT; only a first sighting writes.
        if (score := self.peek(subject_type, subject_id)) is not None:
            return score
        with transaction() as db:
            _ensure(db, subject_type, subject_id, initial)
            return db.execute(
                select(TrustScoreRow.score).where(_key(subject_type, subject_id))
            ).scalar_one()

    def peek(self, subject_type: SubjectType, subject_id: str) -> float | None:
        with transaction() as db:
            return db.scalar(select(TrustScoreRow.score).where(_key(subject_type, subject_id)))

    def update(
        self,
        subject_type: SubjectType,
        subject_id: str,
        initial: float,
        compute: Compute,
        *,
        signal: str,
        rationale: str | None,
        assessed_by: str,
    ) -> TrustAssessmentRecord:
        with transaction() as db:
            _ensure(db, subject_type, subject_id, initial)
            row = db.scalars(
                select(TrustScoreRow).where(_key(subject_type, subject_id)).with_for_update()
            ).one()
            previous = row.score
            row.score = round(clamp(compute(previous)), 4)
            row.assessments += 1
            record = make_record(
                row.subject_type,
                row.subject_id,
                previous,
                row.score,
                signal=signal,
                rationale=rationale,
                assessed_by=assessed_by,
            )
            row.updated_at = record.created_at
            db.add(
                TrustAssessment(
                    subject_type=row.subject_type,
                    subject_key=row.subject_key,
                    subject_id=row.subject_id,
                    score=record.score,
                    previous=previous,
                    level=record.level,
                    signal=signal,
                    rationale=rationale,
                    assessed_by=assessed_by,
                    created_at=record.created_at,
                )
            )
            return record

    def detail(self, subject_type: SubjectType, subject_id: str) -> TrustScoreDetail | None:
        with transaction() as db:
            row = db.scalars(select(TrustScoreRow).where(_key(subject_type, subject_id))).first()
            if row is None:
                return None
            history = db.scalars(
                select(TrustAssessment)
                .where(
                    (TrustAssessment.subject_type == subject_type)
                    & (TrustAssessment.subject_key == subject_id.lower())
                )
                .order_by(TrustAssessment.created_at.desc())
                .limit(HISTORY_LEN)
            ).all()
            return TrustScoreDetail(
                **_summary(row).model_dump(),
                history=[
                    TrustAssessmentRecord(
                        subject_type=h.subject_type,
                        subject_id=h.subject_id,
                        score=h.score,
                        previous=h.previous,
                        level=h.level,
                        signal=h.signal,
                        rationale=h.rationale,
                        assessed_by=h.assessed_by or "trust-engine",
                        created_at=h.created_at,
                    )
                    for h in history
                ],
            )

    def list(self, subject_type: SubjectType | None) -> list[TrustScore]:
        query = select(TrustScoreRow).order_by(TrustScoreRow.score)
        if subject_type is not None:
            query = query.where(TrustScoreRow.subject_type == subject_type)
        with transaction() as db:
            return [_summary(row) for row in db.scalars(query)]

    def clear(self) -> None:
        with transaction() as db:
            db.execute(delete(TrustAssessment))
            db.execute(delete(TrustScoreRow))

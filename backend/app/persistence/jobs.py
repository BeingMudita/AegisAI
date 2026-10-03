"""Ingestion jobs shared through ``ingest_jobs``.

A job is processed by the worker that received the file (it lives on that
worker's disk), but its state is published here so any worker can list it,
report its progress, or cancel it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.database.models import IngestJobRow
from app.database.sync import transaction
from app.rag.ingestion import IngestionManager
from app.rag.schemas import IngestJob, IngestStage

_LIST_LIMIT = 500


class PostgresIngestionManager(IngestionManager):
    def _publish(self, job: IngestJob) -> None:
        payload = job.model_dump(mode="json")
        stmt = insert(IngestJobRow).values(
            id=job.id, stage=job.stage.value, payload=payload, updated_at=datetime.now(timezone.utc)
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[IngestJobRow.id],
            # Never let a late progress report undo a cancellation made elsewhere.
            set_={
                "stage": stmt.excluded.stage,
                "payload": stmt.excluded.payload,
                "updated_at": stmt.excluded.updated_at,
            },
            where=IngestJobRow.payload["cancel_requested"].astext.is_distinct_from("true")
            | (
                stmt.excluded.stage.in_(
                    [
                        s.value
                        for s in (IngestStage.CANCELLED, IngestStage.FAILED, IngestStage.COMPLETED)
                    ]
                )
            ),
        )
        with transaction() as db:
            db.execute(stmt)

    def list_jobs(self) -> list[IngestJob]:
        with transaction() as db:
            rows = db.scalars(
                select(IngestJobRow).order_by(IngestJobRow.updated_at.desc()).limit(_LIST_LIMIT)
            ).all()
            return [IngestJob.model_validate(r.payload) for r in rows]

    def get(self, job_id: str) -> IngestJob | None:
        with transaction() as db:
            row = db.get(IngestJobRow, job_id)
            return IngestJob.model_validate(row.payload) if row else None

    def cancel(self, job_id: str) -> IngestJob | None:
        local = super().cancel(job_id)  # this worker owns the job → cancels directly
        if local is not None:
            return local
        with transaction() as db:  # another worker owns it → flag it; that worker polls
            row = db.get(IngestJobRow, job_id, with_for_update=True)
            if row is None:
                return None
            job = IngestJob.model_validate(row.payload)
            if not job.done:
                row.payload = {**row.payload, "cancel_requested": True}
            return job

    def _should_cancel(self, job_id: str) -> bool:
        if super()._should_cancel(job_id):
            return True
        with transaction() as db:
            row = db.get(IngestJobRow, job_id)
            return bool(row and row.payload.get("cancel_requested"))

    def truncate_for_tests(self) -> None:
        with transaction() as db:
            db.execute(delete(IngestJobRow))

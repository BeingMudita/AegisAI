"""Red-team run history in ``redteam_runs`` (the full report as JSON)."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.database.models import RedTeamRunRow
from app.database.sync import transaction
from app.redteam.schemas import RedTeamRun


class PostgresRunStore:
    def save(self, run: RedTeamRun) -> None:
        values = {
            "status": run.status,
            "started_at": run.started_at,
            "payload": run.model_dump(mode="json"),
        }
        stmt = insert(RedTeamRunRow).values(id=run.id, **values)
        stmt = stmt.on_conflict_do_update(index_elements=[RedTeamRunRow.id], set_=values)
        with transaction() as db:
            db.execute(stmt)

    def get(self, run_id: str) -> RedTeamRun | None:
        with transaction() as db:
            row = db.get(RedTeamRunRow, run_id)
            return RedTeamRun.model_validate(row.payload) if row else None

    def recent(self, limit: int) -> list[RedTeamRun]:
        query = select(RedTeamRunRow).order_by(RedTeamRunRow.started_at.desc()).limit(limit)
        with transaction() as db:
            return [RedTeamRun.model_validate(row.payload) for row in db.scalars(query)]

    def clear(self) -> None:
        with transaction() as db:
            db.execute(delete(RedTeamRunRow))

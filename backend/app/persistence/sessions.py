"""Durable sessions: ``agent_sessions``, ``session_runs`` and ``agent_turns``.

Coordination works across API workers:

* **One turn at a time** — ``begin_turn`` locks the session row and refuses if a
  run is ``running`` with an unexpired lease.
* **Crash recovery** — a run's lease (``SESSION_LEASE_SECONDS``, extended on each
  progress report) lets a session recover if the worker running it dies.
* **Replay rejection** — the unique (session_id, request_id) constraint rejects a
  repeated request ID on any worker, permanently, even after a failed attempt.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, exists, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.schemas import (
    AgentSessionRecord,
    AgentTurn,
    RunProgress,
    SessionSummary,
    TraceEntry,
)
from app.agents.sessions import SessionStore, expired_message, idle_cutoff
from app.config import get_settings
from app.database.enums import SessionStatus
from app.database.models import Agent, AgentSession, AgentTurnRow, SessionRun, User
from app.database.sync import transaction

_ALREADY_ATTEMPTED = "Request already attempted. Review the session before retrying."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _lease() -> datetime:
    return _now() + timedelta(seconds=get_settings().session_lease_seconds)


def _progress(run: SessionRun) -> RunProgress:
    return RunProgress(
        request_id=run.request_id,
        status=run.status,  # type: ignore[arg-type]
        current_stage=run.current_stage,
        stages=[TraceEntry.model_validate(s) for s in run.stages or []],
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def _agent_id(db: Session, name: str) -> uuid.UUID:
    db.execute(insert(Agent).values(id=uuid.uuid4(), name=name).on_conflict_do_nothing())
    return db.execute(select(Agent.id).where(Agent.name == name)).scalar_one()


class PostgresSessionStore(SessionStore):
    # ------------------------------------------------------------ sessions
    def create(self, agent: str, owner: str) -> AgentSessionRecord:
        record = AgentSessionRecord(agent=agent, owner=owner)
        with transaction() as db:
            db.add(
                AgentSession(
                    id=uuid.UUID(record.id),
                    agent_id=_agent_id(db, agent),
                    user_id=db.scalar(select(User.id).where(User.username == owner)),
                    status=record.status,
                    meta={"owner": owner},
                    started_at=record.created_at,
                    last_activity_at=record.created_at,
                )
            )
        return record

    @staticmethod
    def _head(db: Session, sid: uuid.UUID) -> AgentSessionRecord | None:
        hit = db.execute(
            select(AgentSession, Agent.name)
            .join(Agent, Agent.id == AgentSession.agent_id)
            .where(AgentSession.id == sid)
        ).first()
        if hit is None:
            return None
        row, agent = hit
        return AgentSessionRecord(
            id=str(row.id),
            agent=agent or "",
            owner=(row.meta or {}).get("owner", ""),
            status=row.status,
            created_at=row.started_at,
            ended_at=row.ended_at,
        )

    def head(self, session_id: str) -> AgentSessionRecord | None:
        sid = _uuid(session_id)
        if sid is None:
            return None
        with transaction() as db:
            return self._head(db, sid)

    def get(self, session_id: str) -> AgentSessionRecord | None:
        sid = _uuid(session_id)
        if sid is None:
            return None
        with transaction() as db:
            record = self._head(db, sid)
            if record is None:
                return None
            turns = db.scalars(
                select(AgentTurnRow.payload)
                .where(AgentTurnRow.session_id == sid)
                .order_by(AgentTurnRow.created_at)
            ).all()
            record.turns = [AgentTurn.model_validate(t) for t in turns]
            return record

    def list(
        self,
        owner: str | None = None,
        *,
        limit: int | None = None,
        before: tuple[datetime, str] | None = None,
    ) -> list[SessionSummary]:
        counts = (
            select(
                AgentTurnRow.session_id,
                func.count().label("turns"),
                func.count().filter(AgentTurnRow.blocked).label("blocked"),
            )
            .group_by(AgentTurnRow.session_id)
            .subquery()
        )
        query = (
            select(AgentSession, Agent.name, counts.c.turns, counts.c.blocked)
            .join(Agent, Agent.id == AgentSession.agent_id)
            .outerjoin(counts, counts.c.session_id == AgentSession.id)
            .order_by(AgentSession.started_at.desc(), AgentSession.id.desc())
        )
        if owner is not None:
            query = query.where(AgentSession.meta["owner"].astext == owner)
        if before is not None:
            key = _uuid(before[1])
            if key is None:
                return []
            query = query.where(tuple_(AgentSession.started_at, AgentSession.id) < (before[0], key))
        if limit is not None:
            query = query.limit(limit)
        with transaction() as db:
            return [
                SessionSummary(
                    id=str(row.id),
                    agent=agent,
                    owner=(row.meta or {}).get("owner", ""),
                    status=row.status,
                    created_at=row.started_at,
                    ended_at=row.ended_at,
                    turns=turns or 0,
                    blocked_turns=blocked or 0,
                )
                for row, agent, turns, blocked in db.execute(query)
            ]

    @staticmethod
    def _insert_turn(db: Session, sid: uuid.UUID, turn: AgentTurn, request_id: str | None) -> None:
        db.add(
            AgentTurnRow(
                id=uuid.UUID(turn.id),
                session_id=sid,
                request_id=request_id,
                blocked=turn.blocked,
                payload=turn.model_dump(mode="json"),
                created_at=turn.created_at,
            )
        )

    def close(
        self, session_id: str, status: SessionStatus = SessionStatus.CLOSED
    ) -> AgentSessionRecord | None:
        sid = _uuid(session_id)
        if sid is None:
            return None
        with transaction() as db:
            row = db.get(AgentSession, sid, with_for_update=True)
            if row is None:
                return None
            if self._running(db, sid) is not None:
                raise ValueError("Wait for the running turn before closing this session.")
            if row.status == SessionStatus.ACTIVE:
                row.status = status
                row.ended_at = _now()
        return self.get(session_id)

    # ---------------------------------------------------------------- runs
    @staticmethod
    def _running(db: Session, sid: uuid.UUID) -> SessionRun | None:
        """The live run of a session; runs whose lease expired are failed first."""
        now = _now()
        for run in db.scalars(
            select(SessionRun).where(
                (SessionRun.session_id == sid) & (SessionRun.status == "running")
            )
        ):
            if run.lease_expires_at and run.lease_expires_at > now:
                return run
            run.status = "failed"
            run.finished_at = now
            run.current_stage = None
        return None

    def begin_turn(self, session_id: str, request_id: str) -> None:
        sid = uuid.UUID(session_id)
        refusal: str | None = None
        try:
            with transaction() as db:
                session = db.get(AgentSession, sid, with_for_update=True)
                if session is None:
                    raise KeyError(session_id)
                cutoff = idle_cutoff()
                last = session.last_activity_at or session.started_at
                if session.status == SessionStatus.ACTIVE and cutoff and last < cutoff:
                    # Recorded as a refusal (not raised) so the expiry is committed.
                    session.status = SessionStatus.EXPIRED
                    session.ended_at = _now()
                if session.status == SessionStatus.EXPIRED:
                    refusal = expired_message()
                elif session.status != SessionStatus.ACTIVE:
                    refusal = "Session is closed."
                elif self._running(db, sid) is not None:
                    raise ValueError("A turn is already running in this session.")
                else:
                    db.add(
                        SessionRun(
                            session_id=sid,
                            request_id=request_id,
                            status="running",
                            stages=[],
                            started_at=_now(),
                            lease_expires_at=_lease(),
                        )
                    )
                    db.flush()
        except IntegrityError as exc:
            raise ValueError(_ALREADY_ATTEMPTED) from exc
        if refusal is not None:
            raise ValueError(refusal)

    def report_progress(self, session_id: str, entry: TraceEntry) -> None:
        sid = uuid.UUID(session_id)
        with transaction() as db:
            run = db.scalars(
                select(SessionRun)
                .where((SessionRun.session_id == sid) & (SessionRun.status == "running"))
                .order_by(SessionRun.started_at.desc())
                .limit(1)
                .with_for_update()
            ).first()
            if run is None:
                return
            stages = [s for s in run.stages or [] if s.get("stage") != entry.stage]
            run.stages = [*stages, entry.model_dump(mode="json")]
            run.current_stage = entry.stage
            run.lease_expires_at = _lease()

    def finish_turn(self, session_id: str, turn: AgentTurn | None) -> None:
        sid = uuid.UUID(session_id)
        with transaction() as db:
            run = db.scalars(
                select(SessionRun)
                .where((SessionRun.session_id == sid) & (SessionRun.status == "running"))
                .order_by(SessionRun.started_at.desc())
                .limit(1)
                .with_for_update()
            ).first()
            if turn is not None:
                self._insert_turn(db, sid, turn, run.request_id if run else None)
                db.execute(
                    update(AgentSession)
                    .where(AgentSession.id == sid)
                    .values(last_activity_at=turn.created_at)
                )
            if run is None:
                return
            run.status = "failed" if turn is None else "blocked" if turn.blocked else "completed"
            if turn is None:
                run.stages = [
                    {**s, "status": "failed"} if s.get("status") == "running" else s
                    for s in run.stages or []
                ]
            run.finished_at = _now()
            run.current_stage = None

    def progress(self, session_id: str) -> RunProgress | None:
        sid = _uuid(session_id)
        if sid is None:
            return None
        with transaction() as db:
            run = db.scalars(
                select(SessionRun)
                .where(SessionRun.session_id == sid)
                .order_by(SessionRun.started_at.desc())
                .limit(1)
            ).first()
            return _progress(run) if run else None

    # ------------------------------------------------------------ retention
    def expire_idle(self, cutoff: datetime) -> int:
        now = _now()
        live_run = exists().where(
            (SessionRun.session_id == AgentSession.id)
            & (SessionRun.status == "running")
            & (SessionRun.lease_expires_at > now)
        )
        stmt = (
            update(AgentSession)
            .where(
                (AgentSession.status == SessionStatus.ACTIVE)
                & (func.coalesce(AgentSession.last_activity_at, AgentSession.started_at) < cutoff)
                & ~live_run
            )
            .values(status=SessionStatus.EXPIRED, ended_at=now)
        )
        with transaction() as db:
            return int(db.execute(stmt).rowcount or 0)  # type: ignore[attr-defined]

    def purge_ended_before(self, cutoff: datetime) -> int:
        """Delete ended sessions; their runs and turns go with them (ON DELETE CASCADE)."""
        stmt = delete(AgentSession).where(
            (AgentSession.status != SessionStatus.ACTIVE) & (AgentSession.ended_at < cutoff)
        )
        with transaction() as db:
            return int(db.execute(stmt).rowcount or 0)  # type: ignore[attr-defined]

    def clear(self) -> None:
        with transaction() as db:
            db.execute(delete(AgentTurnRow))
            db.execute(delete(SessionRun))
            db.execute(delete(AgentSession))

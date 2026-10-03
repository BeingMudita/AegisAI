"""Guarantees that only matter with several API workers sharing one database.

Each test builds two independent store instances on the same database — two
"workers" — and checks they coordinate. Skipped unless the suite runs against
Postgres (``AEGIS_TEST_POSTGRES=1`` or ``TEST_DATABASE_URL``; see conftest).
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient

from tests.conftest import POSTGRES

pytestmark = pytest.mark.skipif(not POSTGRES, reason="needs PostgreSQL (see tests/conftest.py)")

if POSTGRES:
    from app.agents.schemas import AgentTurn
    from app.database.enums import SecurityEventType, SecuritySeverity, SubjectType
    from app.database.models import Base
    from app.database.sync import get_sync_engine
    from app.main import app
    from app.persistence import sessions as pg_sessions
    from app.persistence.audit import AuditClearForbidden, PostgresAuditLog
    from app.persistence.jobs import PostgresIngestionManager
    from app.persistence.ratelimit import PostgresLoginLimiter, PostgresRateLimiter
    from app.persistence.sessions import PostgresSessionStore
    from app.persistence.trust import PostgresTrustRepository
    from app.rag.knowledge_base import get_knowledge_base
    from app.rag.schemas import IngestJob, IngestStage
    from app.trust.engine import TrustEngine


def _turn(session_id: str, message: str = "hi") -> AgentTurn:
    return AgentTurn(
        session_id=session_id, agent="FinanceAgent", message=message, answer="ok", brain="t"
    )


# ----------------------------------------------------------------- schema
def test_migrations_match_models() -> None:
    with get_sync_engine().connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []


# --------------------------------------------------------------- sessions
def test_one_turn_at_a_time_across_workers() -> None:
    a, b = PostgresSessionStore(), PostgresSessionStore()
    session = a.create("FinanceAgent", "admin")
    a.begin_turn(session.id, "req-1")
    with pytest.raises(ValueError, match="already running"):
        b.begin_turn(session.id, "req-2")
    with pytest.raises(ValueError, match="running turn"):
        b.close(session.id)
    a.finish_turn(session.id, _turn(session.id))
    b.begin_turn(session.id, "req-2")  # released
    b.finish_turn(session.id, _turn(session.id, "second"))
    assert [t.message for t in a.get(session.id).turns] == ["hi", "second"]


def test_request_id_replay_rejected_on_any_worker() -> None:
    a, b = PostgresSessionStore(), PostgresSessionStore()
    session = a.create("FinanceAgent", "admin")
    a.begin_turn(session.id, "req-x")
    a.finish_turn(session.id, None)  # failed attempt still counts
    with pytest.raises(ValueError, match="already attempted"):
        b.begin_turn(session.id, "req-x")
    assert b.progress(session.id).status == "failed"


def test_expired_lease_frees_a_session_held_by_a_dead_worker(monkeypatch) -> None:
    a, b = PostgresSessionStore(), PostgresSessionStore()
    session = a.create("FinanceAgent", "admin")
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    monkeypatch.setattr(pg_sessions, "_lease", lambda: past)
    a.begin_turn(session.id, "req-dead")  # worker A "crashes" holding an expired lease
    monkeypatch.undo()
    b.begin_turn(session.id, "req-new")
    assert b.progress(session.id).request_id == "req-new"


def test_progress_is_visible_from_another_worker() -> None:
    from app.agents.schemas import TraceEntry

    a, b = PostgresSessionStore(), PostgresSessionStore()
    session = a.create("FinanceAgent", "admin")
    a.begin_turn(session.id, "req-p")
    a.report_progress(session.id, TraceEntry(stage="retrieval", status="running", detail="x"))
    progress = b.progress(session.id)
    assert (progress.status, progress.current_stage) == ("running", "retrieval")


# ------------------------------------------------------------------ trust
def test_concurrent_trust_updates_are_never_lost() -> None:
    workers = [TrustEngine(repository=PostgresTrustRepository()) for _ in range(2)]
    workers[0].override(SubjectType.AGENT, "Racer", 1.0, rationale="start", assessed_by="t")

    def penalize(engine: TrustEngine) -> None:
        for _ in range(10):
            engine.repo.update(
                SubjectType.AGENT, "Racer", 1.0, lambda s: s - 0.01,
                signal="TEST", rationale=None, assessed_by="t",
            )  # fmt: skip

    threads = [threading.Thread(target=penalize, args=(w,)) for w in workers for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert workers[1].score(SubjectType.AGENT, "Racer") == pytest.approx(0.6)  # 1.0 - 40 × 0.01
    assert workers[1].get(SubjectType.AGENT, "Racer").assessments == 41


# ------------------------------------------------------------- rate limits
def test_rate_limit_is_shared_across_workers() -> None:
    a, b = PostgresRateLimiter(), PostgresRateLimiter()
    key = "tool:test:shared"
    assert [a.try_acquire(key, limit=3, window_seconds=60) for _ in range(2)] == [0, 0]
    assert b.try_acquire(key, limit=3, window_seconds=60) == 0
    assert a.try_acquire(key, limit=3, window_seconds=60) > 0
    assert b.try_acquire(key, limit=3, window_seconds=60) > 0


def test_login_throttle_is_shared_across_workers() -> None:
    a, b = PostgresLoginLimiter(limit=2), PostgresLoginLimiter(limit=2)
    assert (a.retry_after("10.0.0.9"), b.retry_after("10.0.0.9")) == (0, 0)
    assert a.retry_after("10.0.0.9") > 0
    assert b.retry_after("10.0.0.10") == 0  # other peers unaffected


# -------------------------------------------------------------- durability
def test_audit_log_is_durable_and_not_erasable() -> None:
    PostgresAuditLog().record_event(
        event_type=SecurityEventType.ANOMALY,
        severity=SecuritySeverity.LOW,
        source="test",
        description="kept",
    )
    fresh = PostgresAuditLog()  # e.g. after a restart
    assert fresh.list_events()[0].description == "kept"
    with pytest.raises(AuditClearForbidden):
        fresh.clear()

    client = TestClient(app)
    token = client.post(
        "/api/auth/login", data={"username": "admin", "password": "admin123"}
    ).json()["access_token"]
    resp = client.delete("/api/security-events", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 409


def test_knowledge_base_lives_in_pgvector() -> None:
    kb = get_knowledge_base()
    stats = kb.stats()
    assert stats.persisted and stats.chunks_indexed > 0
    assert kb.retrieve("invoice approval thresholds").chunks[0].source == "Finance Handbook"
    assert kb.quarantine()[0].source == "Vendor Portal"


def test_ingest_job_visible_and_cancellable_from_another_worker(tmp_path) -> None:
    kb = get_knowledge_base()
    a = PostgresIngestionManager(kb, inbox_dir=tmp_path, upload_dir=tmp_path)
    b = PostgresIngestionManager(kb, inbox_dir=tmp_path, upload_dir=tmp_path)
    job = IngestJob(
        filename="big.txt", title="big.txt", source="S", trust_level="MEDIUM",
        origin="inbox", size_bytes=10, stage=IngestStage.PARSING,
    )  # fmt: skip
    a._publish(job)  # worker A is processing it
    assert b.get(job.id).stage == IngestStage.PARSING
    b.cancel(job.id)  # worker B asks to cancel
    assert a._should_cancel(job.id)

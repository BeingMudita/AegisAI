"""Shared fixtures — isolate the stores between tests.

The suite runs against the in-memory stores by default. To run the very same
tests against PostgreSQL (``STORAGE_BACKEND=postgres``):

    AEGIS_TEST_POSTGRES=1 pytest                      # embedded server via `pgserver`
    TEST_DATABASE_URL=postgresql://… pytest           # an existing (throwaway!) database

The database is migrated and seeded first; tables are truncated between tests.
"""

from __future__ import annotations

import os
import tempfile

# Deterministic, offline backends for tests — set before any app module reads settings.
os.environ.setdefault("LLM_BACKEND", "rule_based")
os.environ.setdefault("EMBEDDING_BACKEND", "hashing")
os.environ.setdefault("RAG_PERSIST", "false")  # never touch backend/data from tests
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="aegis-test-data-"))

POSTGRES = bool(os.environ.get("TEST_DATABASE_URL") or os.environ.get("AEGIS_TEST_POSTGRES"))
_PG_SERVER = None
if POSTGRES:
    _url = os.environ.get("TEST_DATABASE_URL")
    if not _url:
        import pgserver

        _PG_SERVER = pgserver.get_server(
            tempfile.mkdtemp(prefix="aegis-test-pg-"), cleanup_mode="stop"
        )
        _url = _PG_SERVER.get_uri()
    os.environ["STORAGE_BACKEND"] = "postgres"
    os.environ["DATABASE_URL"] = _url

    from app.config import get_settings  # noqa: E402
    from app.database.migrate import upgrade  # noqa: E402
    from app.persistence.seed import seed_reference_data  # noqa: E402

    upgrade(get_settings().sync_database_url)
    seed_reference_data()

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402

from app.agents.sessions import get_session_store  # noqa: E402
from app.auth.limiter import login_limiter  # noqa: E402
from app.platform.adaptive import get_adaptive_monitor  # noqa: E402
from app.redteam.service import get_redteam_service  # noqa: E402
from app.telemetry.store import get_audit_log  # noqa: E402
from app.tools.gateway import get_tool_gateway  # noqa: E402
from app.tools.sandbox import OUTBOX  # noqa: E402
from app.trust.engine import get_trust_engine  # noqa: E402


def _clear() -> None:
    login_limiter.clear()
    audit = get_audit_log()
    if POSTGRES:
        audit.truncate_for_tests()  # type: ignore[attr-defined]  (durable log refuses clear())
    else:
        audit.clear()
    get_trust_engine().clear()
    get_tool_gateway().clear()
    get_session_store().clear()
    get_redteam_service().store.clear()
    get_adaptive_monitor().clear()
    OUTBOX.clear()


@pytest.fixture(autouse=True)
def _reset_state() -> Iterator[None]:
    _clear()
    yield
    _clear()

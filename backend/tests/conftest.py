"""Shared fixtures — isolate the in-memory stores between tests."""

from __future__ import annotations

import os
import tempfile

# Deterministic, offline backends for tests — set before any app module reads settings.
os.environ.setdefault("LLM_BACKEND", "rule_based")
os.environ.setdefault("EMBEDDING_BACKEND", "hashing")
os.environ.setdefault("RAG_PERSIST", "false")  # never touch backend/data from tests
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="aegis-test-data-"))

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402

from app.agents.sessions import get_session_store  # noqa: E402
from app.telemetry.store import get_audit_log  # noqa: E402
from app.tools.gateway import get_tool_gateway  # noqa: E402
from app.tools.sandbox import OUTBOX  # noqa: E402
from app.trust.engine import get_trust_engine  # noqa: E402


def _clear() -> None:
    get_audit_log().clear()
    get_trust_engine().clear()
    get_tool_gateway().clear()
    get_session_store().clear()
    OUTBOX.clear()


@pytest.fixture(autouse=True)
def _reset_state() -> Iterator[None]:
    _clear()
    yield
    _clear()

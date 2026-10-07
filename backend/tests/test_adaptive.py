"""Tests for runtime adaptive security (behaviour → trust → posture → enforcement)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.database.enums import SubjectType
from app.main import app
from app.platform.adaptive import AgentPosture, get_adaptive_monitor, posture_for
from app.platform.policyfile import (
    AegisFile,
    AgentSection,
    DomainsSection,
    PermissionsSection,
    TrustSection,
)
from app.platform.protocol.events import AegisEventType
from app.platform.protocol.schemas import AegisDecision, Decision
from app.policies import store as policy_store
from app.trust.engine import get_trust_engine

client = TestClient(app)
AGENT = "adaptive-agent"


@pytest.fixture(autouse=True)
def _policy() -> Iterator[None]:
    AegisFile(
        agent=AgentSection(name=AGENT),
        permissions=PermissionsSection(tools=["read_database", "send_email", "search_documents"]),
        domains=DomainsSection(allowed=["company.com"]),
        trust=TrustSection(minimum=0.60),
    ).apply()
    get_adaptive_monitor().clear()
    yield
    policy_store.clear_overrides()
    get_adaptive_monitor().clear()


def _allow() -> AegisDecision:
    return AegisDecision(
        decision=Decision.ALLOW,
        reason="ok",
        event_type=AegisEventType.TOOL_PROPOSAL,
        agent=AGENT,
        session_id="s",
    )


def test_posture_thresholds() -> None:
    assert posture_for(0.9) is AgentPosture.NORMAL
    assert posture_for(0.5) is AgentPosture.SUSPICIOUS
    assert posture_for(0.3) is AgentPosture.RESTRICTED
    assert posture_for(0.1) is AgentPosture.QUARANTINED


def test_quarantined_agent_is_blocked_on_everything() -> None:
    get_trust_engine().override(SubjectType.AGENT, AGENT, 0.1, rationale="test", assessed_by="t")
    decision = get_adaptive_monitor().apply(AGENT, "read_database", _allow(), {"query": "1"})
    assert decision.decision is Decision.BLOCK
    assert decision.reason_code == "posture_quarantined"


def test_restricted_agent_blocks_risky_but_allows_safe() -> None:
    monitor = get_adaptive_monitor()
    get_trust_engine().override(SubjectType.AGENT, AGENT, 0.3, rationale="test", assessed_by="t")
    risky = monitor.apply(AGENT, "send_email", _allow(), {"to": "x@company.com"})
    assert risky.decision is Decision.BLOCK
    assert risky.reason_code == "posture_restricted"
    safe = monitor.apply(AGENT, "search_documents", _allow(), {"query": "q"})
    assert safe.decision is Decision.ALLOW


def test_suspicious_agent_escalates_risky_tool_to_approval() -> None:
    get_trust_engine().override(SubjectType.AGENT, AGENT, 0.5, rationale="test", assessed_by="t")
    decision = get_adaptive_monitor().apply(AGENT, "send_email", _allow(), {"to": "x@company.com"})
    assert decision.decision is Decision.APPROVAL
    assert decision.reason_code == "posture_review"


def test_behavioral_anomaly_degrades_trust() -> None:
    monitor = get_adaptive_monitor()
    trust = get_trust_engine()
    # Establish a baseline of read_database, then deviate to a new tool.
    for _ in range(5):
        monitor.apply(AGENT, "read_database", _allow(), {"query": "1"})
    before = trust.score(SubjectType.AGENT, AGENT)
    monitor.apply(AGENT, "search_documents", _allow(), {"query": "q"})  # new_tool anomaly
    after = trust.score(SubjectType.AGENT, AGENT)
    assert after < before
    assert monitor.state(AGENT).anomalies >= 1


def test_adaptive_state_endpoint() -> None:
    token = _token()
    resp = client.get(f"/api/adaptive/agents/{AGENT}", headers=token)
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent"] == AGENT
    assert body["posture"] == "NORMAL"


def test_adaptive_reset_requires_admin() -> None:
    # analyst may read, but not reset.
    analyst = _token("analyst", "analyst123")
    assert client.post(f"/api/adaptive/agents/{AGENT}/reset", headers=analyst).status_code == 403
    admin = _token()
    assert client.post(f"/api/adaptive/agents/{AGENT}/reset", headers=admin).status_code == 200


def _token(user: str = "admin", pw: str = "admin123") -> dict[str, str]:
    resp = client.post("/api/auth/login", data={"username": user, "password": pw})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}

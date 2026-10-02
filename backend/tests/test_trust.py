"""Tests for the trust engine (Phase 4)."""

from fastapi.testclient import TestClient

from app.database.enums import SecurityEventType, SubjectType, TrustLevel
from app.main import app
from app.telemetry.store import get_audit_log
from app.trust.engine import TrustEngine, get_trust_engine
from app.trust.scoring import (
    INITIAL_AGENT_TRUST,
    TrustSignal,
    apply_signal,
    level_for,
)

client = TestClient(app)
AGENT = SubjectType.AGENT


def _token(username: str, password: str) -> str:
    resp = client.post("/api/auth/login", data={"username": username, "password": password})
    return resp.json()["access_token"]


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ----------------------------------------------------------------- scoring
def test_level_mapping() -> None:
    assert level_for(0.95) == TrustLevel.VERIFIED
    assert level_for(0.7) == TrustLevel.HIGH
    assert level_for(0.5) == TrustLevel.MEDIUM
    assert level_for(0.3) == TrustLevel.LOW
    assert level_for(0.05) == TrustLevel.UNTRUSTED


def test_penalty_is_fast_reward_is_slow() -> None:
    assert apply_signal(0.75, TrustSignal.FIREWALL_BLOCK) == 0.6
    # Rewards scale with headroom: +0.04 * (1 - 0.6) = +0.016
    assert apply_signal(0.6, TrustSignal.CLEAN_ACTION) == 0.616


def test_scores_are_clamped() -> None:
    assert apply_signal(0.05, TrustSignal.INJECTED_CONTENT) == 0.0
    assert apply_signal(1.0, TrustSignal.CLEAN_ACTION) == 1.0


# ------------------------------------------------------------------ engine
def test_new_agent_starts_at_initial_trust() -> None:
    engine = TrustEngine()
    assert engine.score(AGENT, "FinanceAgent") == INITIAL_AGENT_TRUST


def test_lookup_is_case_insensitive() -> None:
    engine = TrustEngine()
    engine.observe(AGENT, "FinanceAgent", TrustSignal.FIREWALL_BLOCK)
    assert engine.score(AGENT, "financeagent") == 0.6


def test_repeated_attacks_lose_tool_access() -> None:
    engine = TrustEngine(default_threshold=0.6)
    assert engine.evaluate(AGENT, "a", required=0.6).allowed is True
    engine.observe(AGENT, "a", TrustSignal.FIREWALL_BLOCK)  # 0.60
    engine.observe(AGENT, "a", TrustSignal.FIREWALL_BLOCK)  # 0.45
    decision = engine.evaluate(AGENT, "a", required=0.6, action="use read_database")
    assert decision.allowed is False
    assert "below" in decision.reason


def test_suspended_agent_denied_even_for_low_bar() -> None:
    engine = TrustEngine()
    engine.override(AGENT, "a", 0.1, rationale="test", assessed_by="admin")
    decision = engine.evaluate(AGENT, "a", required=0.0)
    assert decision.allowed is False
    assert "suspended" in decision.reason


def test_level_drop_emits_trust_degradation_event() -> None:
    engine = TrustEngine()
    engine.observe(AGENT, "a", TrustSignal.FIREWALL_FLAG)  # 0.75 → 0.70, still HIGH
    assert get_audit_log().list_events() == []
    engine.observe(AGENT, "a", TrustSignal.FIREWALL_BLOCK)  # 0.70 → 0.55, MEDIUM
    events = get_audit_log().list_events()
    assert len(events) == 1
    assert events[0].event_type == SecurityEventType.TRUST_DEGRADATION


def test_source_seeded_from_declared_level() -> None:
    engine = TrustEngine()
    assert engine.register_source("wiki", TrustLevel.UNTRUSTED) == 0.1
    assert engine.register_source("handbook", TrustLevel.VERIFIED) == 0.95
    # re-registering doesn't reset an existing score
    engine.observe(SubjectType.SOURCE, "handbook", TrustSignal.INJECTED_CONTENT)
    assert engine.register_source("handbook", TrustLevel.VERIFIED) == 0.75


def test_history_is_recorded() -> None:
    engine = TrustEngine()
    engine.observe(AGENT, "a", TrustSignal.POLICY_VIOLATION, rationale="tried shell")
    detail = engine.get(AGENT, "a")
    assert detail is not None
    assert detail.assessments == 1
    assert detail.history[0].signal == "POLICY_VIOLATION"
    assert detail.history[0].previous == INITIAL_AGENT_TRUST


# --------------------------------------------------------------------- API
def test_trust_api_list_and_detail() -> None:
    get_trust_engine().observe(AGENT, "FinanceAgent", TrustSignal.FIREWALL_BLOCK)
    analyst = _token("analyst", "analyst123")

    body = client.get("/api/trust", headers=_h(analyst)).json()
    assert body["threshold"] == 0.6
    assert body["scores"][0]["subject_id"] == "FinanceAgent"

    detail = client.get("/api/trust/AGENT/FinanceAgent", headers=_h(analyst))
    assert detail.status_code == 200
    assert detail.json()["score"] == 0.6

    assert client.get("/api/trust/AGENT/nobody", headers=_h(analyst)).status_code == 404


def test_only_admin_can_override() -> None:
    analyst = _token("analyst", "analyst123")
    body = {"score": 0.9, "rationale": "reviewed"}
    assert client.put("/api/trust/AGENT/x", json=body, headers=_h(analyst)).status_code == 403

    admin = _token("admin", "admin123")
    resp = client.put("/api/trust/AGENT/x", json=body, headers=_h(admin))
    assert resp.status_code == 200
    assert resp.json()["assessed_by"] == "admin"
    assert get_trust_engine().score(AGENT, "x") == 0.9


def test_agent_role_cannot_read_trust() -> None:
    agent = _token("agent", "agent123")
    assert client.get("/api/trust", headers=_h(agent)).status_code == 403

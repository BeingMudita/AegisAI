"""Tests for the DevSecOps features: the security gate, the registry, Autopilot."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.platform import autopilot, gate
from app.platform.policyfile import (
    AegisFile,
    AgentSection,
    DomainsSection,
    PermissionsSection,
)
from app.platform.registry import AgentRegistration, get_registry
from app.policies import store as policy_store
from app.policies.store import get_policy
from app.tools.gateway import get_tool_gateway

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolation() -> Iterator[None]:
    get_registry().clear()
    yield
    get_registry().clear()
    policy_store.clear_overrides()


def _token(user: str = "admin", pw: str = "admin123") -> dict[str, str]:
    resp = client.post("/api/auth/login", data={"username": user, "password": pw})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# --------------------------------------------------------------------- gate
def test_gate_passes_a_healthy_agent() -> None:
    result = gate.run_gate("FinanceAgent", threshold=85, redteam=False)
    assert result.passed
    assert result.score >= 85
    assert result.agent == "FinanceAgent"


def test_gate_fails_below_threshold() -> None:
    result = gate.run_gate("FinanceAgent", threshold=100, redteam=False)
    assert not result.passed
    assert any(c.name == "security_score" and not c.passed for c in result.checks)


def test_gate_blocks_wildcard_domain_weakening(tmp_path) -> None:
    # The classic CI catch: a change opens send_email to any destination.
    weak = tmp_path / "aegis.yaml"
    weak.write_text(
        "agent:\n  name: weak-agent\n"
        "permissions:\n  tools: [read_database, send_email]\n"
        'domains:\n  allowed: ["*"]\n'
        "data:\n  deny: [customer_records]\n",
        encoding="utf-8",
    )
    result = gate.run_gate(str(weak), threshold=90, redteam=False)
    assert not result.passed
    assert any("External" in h for h in result.high_findings)


def test_gate_markdown_report() -> None:
    md = gate.render_markdown(gate.run_gate("FinanceAgent", threshold=85, redteam=False))
    assert "AegisAI Security Report" in md
    assert "PASS" in md


def test_gate_api() -> None:
    resp = client.post(
        "/api/gate",
        headers=_token(),
        json={"target": "FinanceAgent", "threshold": 85, "redteam": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["passed"] is True
    assert body["agent"] == "FinanceAgent"


# ----------------------------------------------------------------- registry
def test_registry_onboard_and_protect() -> None:
    reg = get_registry()
    reg.register(
        AgentRegistration(
            id="demo-agent",
            framework="openai-compatible",
            tools=["read_database", "send_email"],
            data=["customer_records"],
        )
    )
    result = reg.onboard("demo-agent", redteam=False)
    assert result.score > 0
    assert "demo-agent" in result.aegis_yaml
    assert result.agent_yaml

    deployment = reg.protect("demo-agent")
    assert deployment["adapter"] == "openai"
    assert "demo-agent" in deployment["aegis_yaml"]
    assert reg.get("demo-agent").status == "protected"


def test_registry_api_flow() -> None:
    token = _token()
    created = client.post(
        "/api/registry/agents",
        headers=token,
        json={"id": "api-agent", "framework": "openai-compatible", "tools": ["read_database"]},
    )
    assert created.status_code == 200
    assert client.get("/api/registry/agents", headers=token).json()
    scan = client.post("/api/registry/agents/api-agent/scan?redteam=false", headers=token)
    assert scan.status_code == 200
    assert scan.json()["agent"] == "api-agent"


def test_registry_scan_unknown_agent_404() -> None:
    assert (
        client.post("/api/registry/agents/ghost/scan?redteam=false", headers=_token()).status_code
        == 404
    )


# ----------------------------------------------------------------- autopilot
def _autopilot_agent() -> None:
    AegisFile(
        agent=AgentSection(name="auto-agent"),
        permissions=PermissionsSection(tools=["read_database", "send_email", "generate_report"]),
        domains=DomainsSection(allowed=["*"]),  # deliberately too broad
    ).apply()


def test_autopilot_recommends_restricting_wildcard_domain() -> None:
    _autopilot_agent()
    recs = autopilot.analyze("auto-agent")
    restrict = next((r for r in recs if r.id == "restrict_domain:*"), None)
    assert restrict is not None
    assert restrict.risk == "HIGH"


def test_autopilot_recommends_removing_unused_tool() -> None:
    _autopilot_agent()
    # Use one tool so the others look unused.
    get_tool_gateway().execute("auto-agent", "read_database", {"query": "1"})
    recs = autopilot.analyze("auto-agent")
    ids = {r.id for r in recs}
    assert "remove_unused_tool:generate_report" in ids


def test_autopilot_apply_tightens_policy() -> None:
    _autopilot_agent()
    autopilot.apply("auto-agent", "restrict_domain:*")
    assert get_policy("auto-agent").allowed_domains == ["company.com"]


def test_autopilot_simulate_scores_without_persisting() -> None:
    _autopilot_agent()
    get_tool_gateway().execute("auto-agent", "read_database", {"query": "1"})
    sim = autopilot.simulate("auto-agent", "remove_unused_tool:generate_report")
    assert sim.score_after >= sim.score_before
    # Simulation must not have changed the live policy.
    assert "generate_report" in get_policy("auto-agent").allowed_tools


def test_autopilot_api_requires_admin_to_apply() -> None:
    _autopilot_agent()
    analyst = _token("analyst", "analyst123")
    recs = client.get("/api/autopilot/agents/auto-agent/recommendations", headers=analyst)
    assert recs.status_code == 200 and recs.json()
    denied = client.post(
        "/api/autopilot/agents/auto-agent/apply",
        headers=analyst,
        json={"recommendation_id": "restrict_domain:*"},
    )
    assert denied.status_code == 403

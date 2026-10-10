"""Multi-agent delegation and tenant isolation, end to end."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.database.enums import ToolRequestStatus
from app.firewall.scanner import PromptFirewall
from app.main import app
from app.orchestration.orchestrator import MultiAgentOrchestrator
from app.policies.config import get_global_config
from app.tenants.schemas import Tenant, TenantPolicy
from app.tenants.store import get_tenant_store
from app.tools.gateway import ToolGateway
from app.trust.engine import TrustEngine

client = TestClient(app)


def _orchestrator(trust: TrustEngine | None = None) -> MultiAgentOrchestrator:
    gw = ToolGateway(
        config=get_global_config(), firewall=PromptFirewall(), trust=trust or TrustEngine()
    )
    return MultiAgentOrchestrator(gateway=gw, trust=gw.trust, tenants=get_tenant_store())


def _token(username: str, password: str) -> str:
    resp = client.post("/api/auth/login", data={"username": username, "password": password})
    return resp.json()["access_token"]


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------- delegation
def test_same_tenant_delegation_runs_the_tool() -> None:
    # Both seed agents are in the default tenant; FinanceAgent asks ResearchAgent
    # (which may web_fetch company.com) to fetch a page.
    result = _orchestrator().delegate(
        caller="FinanceAgent", callee="ResearchAgent", tool="web_fetch",
        arguments={"url": "https://company.com/news"},
    )
    assert result.allowed
    assert result.tool_result is not None
    assert result.tool_result.status == ToolRequestStatus.EXECUTED


def test_cross_tenant_delegation_is_denied() -> None:
    store = get_tenant_store()
    store.create_tenant(Tenant(slug="acme", name="Acme"))
    store.assign_agent("ResearchAgent", "acme")
    result = _orchestrator().delegate(
        caller="FinanceAgent", callee="ResearchAgent", tool="web_fetch",
        arguments={"url": "https://company.com/news"},
    )
    assert not result.allowed
    assert result.checkpoint == "tenant"
    assert result.tool_result is None


def test_tenant_policy_denies_a_tool_through_the_gateway() -> None:
    store = get_tenant_store()
    store.set_policy("default", TenantPolicy(denied_tools=["web_fetch"]))
    result = _orchestrator().delegate(
        caller="FinanceAgent", callee="ResearchAgent", tool="web_fetch",
        arguments={"url": "https://company.com/news"},
    )
    # The delegation itself is permitted (same tenant) but the composed policy
    # blocks the tool at the gateway.
    assert result.allowed and result.tool_result is not None
    assert result.tool_result.status == ToolRequestStatus.DENIED
    assert any(c.checkpoint == "policy" and not c.passed for c in result.tool_result.checks)


def test_delegation_depth_limit() -> None:
    store = get_tenant_store()
    store.set_policy("default", TenantPolicy(max_delegation_depth=1))
    deep = _orchestrator().delegate(
        caller="FinanceAgent", callee="ResearchAgent", tool="web_fetch",
        arguments={"url": "https://company.com/news"}, depth=2,
    )
    assert not deep.allowed and deep.checkpoint == "depth"


# --------------------------------------------------------------- isolation
def test_agents_listing_is_tenant_scoped() -> None:
    admin = _token("admin", "admin123")
    before = {a["name"] for a in client.get("/api/agents", headers=_h(admin)).json()}
    assert {"FinanceAgent", "ResearchAgent"} <= before

    store = get_tenant_store()
    store.create_tenant(Tenant(slug="acme", name="Acme"))
    store.assign_agent("ResearchAgent", "acme")
    after = {a["name"] for a in client.get("/api/agents", headers=_h(admin)).json()}
    assert "ResearchAgent" not in after  # admin is in 'default'; ResearchAgent moved to 'acme'
    assert "FinanceAgent" in after


# --------------------------------------------------------------------- API
def test_delegate_endpoint_requires_admin_and_same_tenant() -> None:
    analyst = _token("analyst", "analyst123")
    body = {"caller": "FinanceAgent", "callee": "ResearchAgent", "tool": "web_fetch",
            "arguments": {"url": "https://company.com/news"}}
    forbidden = client.post("/api/orchestration/delegate", json=body, headers=_h(analyst))
    assert forbidden.status_code == 403

    admin = _token("admin", "admin123")
    ok = client.post("/api/orchestration/delegate", json=body, headers=_h(admin))
    assert ok.status_code == 200 and ok.json()["allowed"] is True

    # Move the callee to another tenant: now the admin (default) may not orchestrate it.
    store = get_tenant_store()
    store.create_tenant(Tenant(slug="acme", name="Acme"))
    store.assign_agent("ResearchAgent", "acme")
    denied = client.post("/api/orchestration/delegate", json=body, headers=_h(admin))
    assert denied.status_code == 403


def test_tenant_crud_endpoints() -> None:
    admin = _token("admin", "admin123")
    created = client.post(
        "/api/tenants", json={"slug": "acme", "name": "Acme Corp"}, headers=_h(admin)
    )
    assert created.status_code == 201
    mine = client.get("/api/tenants/me", headers=_h(admin)).json()
    assert mine["slug"] == "default" and "FinanceAgent" in mine["agents"]
    assigned = client.post("/api/tenants/acme/agents/ResearchAgent", headers=_h(admin)).json()
    assert assigned["agents"] == ["ResearchAgent"]

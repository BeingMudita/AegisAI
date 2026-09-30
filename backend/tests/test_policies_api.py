"""Integration tests for the policy API routes."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _token(username: str, password: str) -> str:
    resp = client.post("/api/auth/login", data={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_list_policies_requires_staff() -> None:
    agent = _token("agent", "agent123")
    assert client.get("/api/policies", headers=_h(agent)).status_code == 403

    admin = _token("admin", "admin123")
    resp = client.get("/api/policies", headers=_h(admin))
    assert resp.status_code == 200
    assert any(p["agent"] == "FinanceAgent" for p in resp.json())


def test_allowances_endpoint() -> None:
    token = _token("analyst", "analyst123")
    resp = client.get("/api/policies/FinanceAgent/allowances", headers=_h(token))
    assert resp.status_code == 200
    assert "shell" in resp.json()["blocked_tools"]


def test_can_use_tool_endpoint() -> None:
    token = _token("agent", "agent123")
    ok = client.get("/api/policies/FinanceAgent/can-use-tool/search_documents", headers=_h(token))
    assert ok.json()["allowed"] is True

    blocked = client.get("/api/policies/FinanceAgent/can-use-tool/shell", headers=_h(token))
    assert blocked.json()["allowed"] is False


def test_unknown_agent_404() -> None:
    token = _token("admin", "admin123")
    resp = client.get("/api/policies/NoSuchAgent/allowances", headers=_h(token))
    assert resp.status_code == 404

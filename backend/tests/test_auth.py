"""Tests for JWT authentication and role-based access control."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _login(username: str, password: str) -> str:
    resp = client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_login_success_and_me() -> None:
    token = _login("admin", "admin123")
    resp = client.get("/api/auth/me", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "admin"
    assert body["role"] == "ADMIN"


def test_login_bad_password() -> None:
    resp = client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "wrong"},
    )
    assert resp.status_code == 401


def test_protected_requires_token() -> None:
    resp = client.get("/api/security-events")
    assert resp.status_code == 401


def test_staff_can_read_security_events() -> None:
    token = _login("analyst", "analyst123")
    resp = client.get("/api/security-events", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_agent_forbidden_from_security_events() -> None:
    token = _login("agent", "agent123")
    resp = client.get("/api/security-events", headers=_auth(token))
    assert resp.status_code == 403


def test_only_admin_can_create_policy() -> None:
    analyst = _login("analyst", "analyst123")
    assert client.post("/api/policies", headers=_auth(analyst)).status_code == 403

    admin = _login("admin", "admin123")
    # Reserved for admins, but not implemented yet — and it says so.
    assert client.post("/api/policies", headers=_auth(admin)).status_code == 501


def test_agent_can_access_sessions() -> None:
    token = _login("agent", "agent123")
    resp = client.get("/api/sessions", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["requested_by"] == "agent"

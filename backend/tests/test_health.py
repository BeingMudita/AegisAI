"""Smoke tests for the application entrypoint."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root() -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "AegisAI"}


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "AegisAI"

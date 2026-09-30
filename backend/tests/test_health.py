"""Smoke tests for the application entrypoint."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root() -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["service"] == "AegisAI"


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"

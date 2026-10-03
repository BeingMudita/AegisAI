from fastapi.testclient import TestClient

from app.auth.limiter import LoginLimiter, login_limiter
from app.main import app


def test_login_is_throttled_even_with_spoofed_forwarding_header() -> None:
    with TestClient(app) as client:
        for _ in range(login_limiter.limit):
            assert login_limiter.retry_after("testclient") == 0
        response = client.post("/api/auth/login", data={"username": "admin", "password": "bad"},
                               headers={"X-Forwarded-For": "different-peer"})
        assert response.status_code == 429
        assert 1 <= int(response.headers["Retry-After"]) <= 60
        assert response.headers["Cache-Control"] == "no-store"


def test_limiter_expires_and_bounds_peer_memory(monkeypatch) -> None:
    clock = [0.0]
    monkeypatch.setattr("app.auth.limiter.time.monotonic", lambda: clock[0])
    limiter = LoginLimiter(limit=2, window=60, capacity=1)
    assert limiter.retry_after("one") == 0
    assert limiter.retry_after("one") == 0
    assert limiter.retry_after("one") == 60
    assert limiter.retry_after("two") == 60
    clock[0] = 60
    assert limiter.retry_after("two") == 0


def test_sensitive_responses_are_not_cached() -> None:
    with TestClient(app) as client:
        response = client.post("/api/auth/login",
                               data={"username": "admin", "password": "admin123"})
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"

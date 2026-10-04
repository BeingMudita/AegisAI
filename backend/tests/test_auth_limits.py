from fastapi.testclient import TestClient

from app.auth.limiter import LoginLimiter, account_limiter, login_limiter
from app.auth.users import get_user
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


def test_failed_sign_ins_are_limited_per_account() -> None:
    # A distributed guessing run: every address stays under its own limit,
    # but the failures pile up on the one account they target.
    for _ in range(account_limiter.limit):
        account_limiter.retry_after("admin")
    with TestClient(app) as client:
        login = {"username": " Admin", "password": "admin123"}
        response = client.post("/api/auth/login", data=login)
        assert response.status_code == 429  # even the right password waits it out
        assert int(response.headers["Retry-After"]) >= 1
        other = {"username": "analyst", "password": "analyst123"}
        assert client.post("/api/auth/login", data=other).status_code == 200


def test_disabled_account_gets_no_token(monkeypatch) -> None:
    analyst = get_user("analyst")
    assert analyst is not None
    disabled = analyst.model_copy(update={"disabled": True})
    monkeypatch.setattr("app.api.routes.auth.get_user", lambda name: disabled)
    with TestClient(app) as client:
        login = {"username": "analyst", "password": "analyst123"}
        assert client.post("/api/auth/login", data=login).status_code == 401

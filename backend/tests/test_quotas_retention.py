"""Phase 10 — per-principal budgets, session expiry, retention and pagination.

Runs on both storage backends (``AEGIS_TEST_POSTGRES=1 pytest`` for PostgreSQL).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents import sessions as memory_sessions
from app.agents.brain import OllamaClient
from app.agents.runtime import get_runtime
from app.agents.sessions import get_session_store
from app.database.enums import SecurityEventType, SecuritySeverity, SessionStatus
from app.main import app
from app.policies.config import BudgetPolicy, get_global_config
from app.quotas.service import BudgetExceeded, QuotaService
from app.quotas.store import get_budget_store
from app.quotas.usage import TokenUsage, metering
from app.retention import run_retention
from app.telemetry.store import get_audit_log

client = TestClient(app)


def _h(username: str, password: str) -> dict[str, str]:
    token = client.post(
        "/api/auth/login", data={"username": username, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def budgets(monkeypatch: pytest.MonkeyPatch):
    """Replace the global budget policy for one test."""

    def set_policy(**fields: object) -> BudgetPolicy:
        policy = BudgetPolicy.model_validate(fields)
        monkeypatch.setattr(get_global_config(), "budgets", policy)
        return policy

    return set_policy


def _quota_events() -> list:
    return [e for e in get_audit_log().list_events(limit=100) if e.source == "quota"]


# ------------------------------------------------------------------ limits
def test_limits_layer_defaults_role_and_principal() -> None:
    policy = BudgetPolicy.model_validate(
        {
            "daily_turns": 10,
            "daily_tokens": 1000,
            "roles": {"ADMIN": {"daily_turns": 50}},
            "principals": {"admin": {"daily_tokens": 5}},
        }
    )
    assert policy.limits_for("someone", None).daily_turns == 10
    admin = policy.limits_for("admin", "ADMIN")
    assert (admin.daily_turns, admin.daily_tokens) == (50, 5)


def test_turn_budget_refuses_and_audits_once(budgets) -> None:
    budgets(daily_turns=2)
    quotas = QuotaService(get_budget_store())
    quotas.start_turn("analyst")
    quotas.start_turn("analyst")
    for _ in range(2):
        with pytest.raises(BudgetExceeded) as exc:
            quotas.start_turn("analyst")
    assert exc.value.status.exhausted == "turns"
    assert 0 < exc.value.retry_after <= 86400
    [event] = _quota_events()  # the first refusal is an incident; retries are not
    assert event.event_type == SecurityEventType.ANOMALY
    assert event.severity == SecuritySeverity.MEDIUM
    quotas.start_turn("admin")  # budgets are per principal


def test_token_and_cost_budgets(budgets) -> None:
    budgets(
        daily_turns=0,
        daily_tokens=100,
        daily_cost_usd=0.01,
        pricing={"prompt_per_1k": 1.0, "completion_per_1k": 2.0},
    )
    quotas = QuotaService(get_budget_store())
    quotas.start_turn("analyst")
    charged = quotas.finish_turn("analyst", TokenUsage(prompt_tokens=4, completion_tokens=3))
    assert charged.cost_usd == pytest.approx(0.01)  # 4 × $1/1k + 3 × $2/1k
    with pytest.raises(BudgetExceeded, match="cost"):
        quotas.start_turn("analyst")

    quotas.finish_turn("admin", TokenUsage(total_tokens=100, estimated=True))
    with pytest.raises(BudgetExceeded, match="token"):
        quotas.check("admin")


# ---------------------------------------------------------------- metering
def test_llm_calls_are_metered_and_capped(budgets, monkeypatch: pytest.MonkeyPatch) -> None:
    budgets(max_output_tokens=256)
    sent: dict = {}

    def fake_post(url: str, json: dict, timeout: float) -> httpx.Response:
        sent.update(json)
        return httpx.Response(
            200,
            json={"message": {"content": "hi"}, "prompt_eval_count": 120, "eval_count": 30},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    llm = OllamaClient("http://ollama", "llama3.1:8b", 5)
    with metering() as meter:
        llm.chat([{"role": "user", "content": "hello"}])
        llm.chat([{"role": "user", "content": "again"}])
    usage = meter.usage()
    assert (usage.prompt_tokens, usage.completion_tokens, usage.llm_calls) == (240, 60, 2)
    assert sent["options"]["num_predict"] == 256


def test_turns_are_charged_to_their_principal_only() -> None:
    runtime = get_runtime()
    turn = runtime.run_turn(
        agent="FinanceAgent", session_id="s", message="What are our payment terms?",
        principal="analyst",
    )  # fmt: skip
    assert turn.usage is not None and turn.usage.estimated and turn.usage.total_tokens > 0
    today = datetime.now(timezone.utc).date()
    used = get_budget_store().get("analyst", today)
    assert (used.turns, used.tokens) == (1, turn.usage.total_tokens)

    runtime.run_turn(agent="FinanceAgent", session_id="s", message="Hello")  # no principal
    assert get_budget_store().list(today, limit=10, offset=0)[1] == 1


# --------------------------------------------------------------------- API
def test_exhausted_budget_is_a_429_and_keeps_the_request_id(budgets) -> None:
    budgets(daily_turns=1)
    headers = _h("analyst", "analyst123")
    sid = client.post("/api/sessions", json={"agent": "FinanceAgent"}, headers=headers).json()["id"]
    ok = client.post(f"/api/sessions/{sid}/messages", json={"message": "hi"}, headers=headers)
    assert ok.status_code == 200 and ok.json()["usage"]["total_tokens"] > 0

    request_id = str(uuid.uuid4())
    body = {"message": "hello again", "request_id": request_id}
    refused = client.post(f"/api/sessions/{sid}/messages", json=body, headers=headers)
    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) > 0
    assert refused.json()["budget"]["exhausted"] == "turns"

    budgets(daily_turns=5)  # e.g. the next day: the same request can still run
    retried = client.post(f"/api/sessions/{sid}/messages", json=body, headers=headers)
    assert retried.status_code == 200


def test_gateway_calls_count_against_the_caller(budgets) -> None:
    budgets(daily_turns=1)
    headers = _h("analyst", "analyst123")
    body = {"agent": "FinanceAgent", "message": "What are our payment terms?"}
    assert client.post("/v1/secure/chat", json=body, headers=headers).status_code == 200
    assert client.post("/v1/secure/chat", json=body, headers=headers).status_code == 429


def test_usage_api() -> None:
    analyst = _h("analyst", "analyst123")
    get_runtime().run_turn(agent="FinanceAgent", session_id="s", message="hi", principal="analyst")
    me = client.get("/api/usage/me", headers=analyst).json()
    assert me["principal"] == "analyst" and me["used"]["turns"] == 1
    assert me["limits"]["daily_turns"] == get_global_config().budgets.daily_turns

    page = client.get("/api/usage?limit=10", headers=analyst).json()
    assert page["total"] == 1 and page["records"][0]["principal"] == "analyst"
    assert client.get("/api/usage", headers=_h("agent", "agent123")).status_code == 403


# ---------------------------------------------------------- session expiry
def test_idle_session_expires_on_its_next_message(monkeypatch: pytest.MonkeyPatch) -> None:
    headers = _h("analyst", "analyst123")
    sid = client.post("/api/sessions", json={"agent": "FinanceAgent"}, headers=headers).json()["id"]

    future = datetime.now(timezone.utc) + timedelta(minutes=1)  # everything is idle
    monkeypatch.setattr(memory_sessions, "idle_cutoff", lambda now=None: future)
    import app.persistence.sessions as pg_sessions

    monkeypatch.setattr(pg_sessions, "idle_cutoff", lambda now=None: future)

    resp = client.post(f"/api/sessions/{sid}/messages", json={"message": "hi"}, headers=headers)
    assert resp.status_code == 409 and "expired" in resp.json()["detail"]
    session = client.get(f"/api/sessions/{sid}", headers=headers).json()
    assert session["status"] == SessionStatus.EXPIRED.value and session["ended_at"]


def test_retention_expires_purges_and_prunes() -> None:
    store = get_session_store()
    idle = store.create("FinanceAgent", "analyst")
    audit = get_audit_log()
    audit.record_event(
        event_type=SecurityEventType.ANOMALY, severity=SecuritySeverity.LOW,
        source="test", description="old",
    )  # fmt: skip
    QuotaService(get_budget_store()).start_turn("analyst")

    later = datetime.now(timezone.utc) + timedelta(days=400)  # past every retention period
    report = run_retention(now=later)
    assert not report.skipped
    assert report.expired_sessions == 1
    assert report.purged_sessions == 1 and store.get(idle.id) is None
    assert report.purged_events >= 1 and audit.list_events() == []
    assert report.purged_usage_rows == 1


def test_retention_keeps_recent_data() -> None:
    store = get_session_store()
    session = store.create("FinanceAgent", "analyst")
    report = run_retention()
    assert (report.expired_sessions, report.purged_sessions, report.purged_events) == (0, 0, 0)
    assert store.get(session.id).status == SessionStatus.ACTIVE


# --------------------------------------------------------------- pagination
def test_sessions_page_with_a_cursor() -> None:
    headers = _h("analyst", "analyst123")
    created = {
        client.post("/api/sessions", json={"agent": "FinanceAgent"}, headers=headers).json()["id"]
        for _ in range(5)
    }
    seen: list[str] = []
    cursor = None
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        page = client.get("/api/sessions", params=params, headers=headers).json()
        seen += [s["id"] for s in page["sessions"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 5 and set(seen) == created
    assert client.get("/api/sessions?cursor=not-a-cursor", headers=headers).status_code == 400


def test_security_events_page_with_a_cursor() -> None:
    audit = get_audit_log()
    for n in range(5):
        audit.record_event(
            event_type=SecurityEventType.ANOMALY, severity=SecuritySeverity.LOW,
            source="test", description=f"event {n}",
        )  # fmt: skip
    headers = _h("analyst", "analyst123")
    first = client.get("/api/security-events?limit=3", headers=headers).json()
    assert first["count"] == 3 and first["next_cursor"]
    rest = client.get(
        "/api/security-events", params={"limit": 3, "cursor": first["next_cursor"]},
        headers=headers,
    ).json()  # fmt: skip
    assert rest["count"] == 2 and rest["next_cursor"] is None
    events = first["events"] + rest["events"]
    # Every event exactly once, newest first (ties on the timestamp break by id).
    assert sorted(e["description"] for e in events) == [f"event {n}" for n in range(5)]
    keys = [(e["created_at"], e["id"]) for e in events]
    assert keys == sorted(keys, reverse=True)

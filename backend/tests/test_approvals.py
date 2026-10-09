"""Human approval workflow for high-impact tool calls (send_email requires approval)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.agents.runtime import get_runtime
from app.database.enums import SecurityEventType, SubjectType, ToolRequestStatus
from app.main import app
from app.telemetry.store import get_audit_log
from app.tools.gateway import ApprovalError, get_tool_gateway
from app.tools.sandbox import OUTBOX
from app.trust.engine import get_trust_engine

client = TestClient(app)
EMAIL = {"to": "cfo@company.com", "subject": "Q3", "body": "Report attached."}


def _h(username: str, password: str) -> dict[str, str]:
    token = client.post(
        "/api/auth/login", data={"username": username, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _queue() -> str:
    result = get_tool_gateway().execute("FinanceAgent", "send_email", EMAIL)
    assert result.status == ToolRequestStatus.PENDING
    return result.id


def test_high_risk_tool_waits_for_a_human() -> None:
    result = get_tool_gateway().execute("FinanceAgent", "send_email", EMAIL)
    assert result.status == ToolRequestStatus.PENDING
    assert [c.checkpoint for c in result.checks] == [
        "registry", "policy", "domain", "firewall", "trust", "rate_limit", "approval",
    ]  # fmt: skip
    assert result.expires_at is not None
    assert OUTBOX == []  # nothing sent yet
    pending, _ = get_tool_gateway().approval_queue()
    assert [p.id for p in pending] == [result.id]


def test_approve_runs_the_tool_after_rechecking() -> None:
    request_id = _queue()
    done = get_tool_gateway().approve(request_id, "admin", "verified with CFO")
    assert done.status == ToolRequestStatus.EXECUTED
    assert done.reviewed_by == "admin" and done.review_note == "verified with CFO"
    assert any(c.checkpoint == "recheck" and c.passed for c in done.checks)
    assert OUTBOX[-1]["to"] == "cfo@company.com"


def test_reject_never_runs_and_costs_trust() -> None:
    request_id = _queue()
    before = get_trust_engine().score(SubjectType.AGENT, "FinanceAgent")
    done = get_tool_gateway().reject(request_id, "admin", "not authorised")
    assert done.status == ToolRequestStatus.DENIED
    assert "Rejected by admin" in done.decision_reason
    assert OUTBOX == []
    assert get_trust_engine().score(SubjectType.AGENT, "FinanceAgent") < before
    assert get_audit_log().list_events()[0].event_type == SecurityEventType.TOOL_DENIED


def test_approval_rechecks_trust_at_decision_time() -> None:
    request_id = _queue()
    get_trust_engine().override(
        SubjectType.AGENT, "FinanceAgent", 0.5, rationale="attacked meanwhile", assessed_by="t"
    )
    done = get_tool_gateway().approve(request_id, "admin")
    assert done.status == ToolRequestStatus.DENIED
    assert "re-check at approval time failed" in done.decision_reason
    assert OUTBOX == []


def test_a_request_can_only_be_decided_once() -> None:
    request_id = _queue()
    get_tool_gateway().approve(request_id, "admin")
    with pytest.raises(ApprovalError):
        get_tool_gateway().approve(request_id, "admin")
    with pytest.raises(ApprovalError):
        get_tool_gateway().reject(request_id, "admin")
    assert len(OUTBOX) == 1


def test_unanswered_requests_expire() -> None:
    gw = get_tool_gateway()
    result = gw.execute("FinanceAgent", "send_email", EMAIL)
    result.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    gw._save_request(result)
    pending, recent = gw.approval_queue()
    assert pending == []
    assert recent[0].status == ToolRequestStatus.DENIED
    assert "expired" in recent[0].decision_reason
    with pytest.raises(ApprovalError):
        gw.approve(result.id, "admin")


def test_agent_reply_says_the_action_awaits_approval() -> None:
    turn = get_runtime().run_turn(
        agent="FinanceAgent",
        session_id="t",
        message="Email the overdue invoices to cfo@company.com",
    )
    call = next(c for c in turn.tool_calls if c.tool == "send_email")
    assert call.status == ToolRequestStatus.PENDING
    assert "Waiting for human approval" in turn.answer
    assert any(e.stage == "tool" and e.status == "pending" for e in turn.trace)


def test_approvals_api_roles() -> None:
    request_id = _queue()
    analyst, admin = _h("analyst", "analyst123"), _h("admin", "admin123")
    queue = client.get("/api/approvals", headers=analyst).json()
    assert queue["pending"][0]["id"] == request_id
    count = client.get("/api/approvals/pending-count", headers=analyst)
    # The badge also counts documents awaiting review (see tests/test_review.py).
    assert count.json()["tools"] == 1
    assert count.json()["pending"] == 1 + count.json()["documents"]
    agent = _h("agent", "agent123")
    assert client.get("/api/approvals/pending-count", headers=agent).status_code == 403
    assert (
        client.post(f"/api/approvals/{request_id}/approve", json={}, headers=analyst).status_code
        == 403
    )
    assert client.get("/api/approvals", headers=_h("agent", "agent123")).status_code == 403

    resp = client.post(f"/api/approvals/{request_id}/approve", json={"note": "ok"}, headers=admin)
    assert resp.status_code == 200 and resp.json()["status"] == "EXECUTED"
    again = client.post(f"/api/approvals/{request_id}/reject", json={}, headers=admin)
    assert again.status_code == 409
    assert client.get("/api/approvals/pending-count", headers=admin).json()["tools"] == 0
    recent = client.get("/api/approvals", headers=admin).json()["recent"]
    assert [r["id"] for r in recent] == [request_id]
    assert client.post("/api/approvals/nope/approve", json={}, headers=admin).status_code == 404

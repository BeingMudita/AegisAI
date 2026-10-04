"""Red-team lab: runs the attack suites in an isolated sandbox."""

import time

import pytest
from fastapi.testclient import TestClient

from app.database.enums import SubjectType
from app.main import app
from app.redteam.schemas import RedTeamRun
from app.redteam.service import RunConflict, get_redteam_service
from app.telemetry.store import get_audit_log
from app.trust.engine import get_trust_engine

client = TestClient(app)


def _h(username: str, password: str) -> dict[str, str]:
    token = client.post(
        "/api/auth/login", data={"username": username, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_full_run_reports_both_suites() -> None:
    run = get_redteam_service().start(["firewall", "agents"], "analyst", wait=True)
    assert run.status == "completed", run.error
    assert run.progress_done == run.progress_total > 0
    assert run.firewall is not None and run.firewall.recall >= 0.9
    assert len(run.firewall.results) == run.firewall.cases
    assert {c.category for c in run.firewall.by_category} >= {"obfuscation", "tool_abuse"}
    assert run.agents is not None and run.agents.passed == run.agents.scenarios


def test_run_is_sandboxed_from_live_state() -> None:
    trust_before = get_trust_engine().list_scores()
    events_before = get_audit_log().summary().total_events
    get_redteam_service().start(["agents"], "analyst", wait=True)
    assert get_audit_log().summary().total_events == events_before  # no simulated attacks logged
    assert get_trust_engine().list_scores() == trust_before  # live trust untouched
    assert get_trust_engine().get(SubjectType.AGENT, "FinanceAgent") is None


def test_only_one_run_at_a_time() -> None:
    service = get_redteam_service()
    service.store.save(RedTeamRun(suites=["firewall"], started_by="x"))  # a run in progress
    with pytest.raises(RunConflict):
        service.start(["firewall"], "analyst")


def test_redteam_api() -> None:
    analyst = _h("analyst", "analyst123")
    assert client.get("/api/redteam/suites", headers=_h("agent", "agent123")).status_code == 403

    suites = client.get("/api/redteam/suites", headers=analyst).json()
    assert suites["firewall"]["cases"] > 0 and suites["agents"]["scenarios"] > 0

    started = client.post("/api/redteam/runs", json={"suites": ["firewall"]}, headers=analyst)
    assert started.status_code == 202
    run_id = started.json()["id"]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        run = client.get(f"/api/redteam/runs/{run_id}", headers=analyst).json()
        if run["status"] != "running":
            break
        time.sleep(0.1)
    assert run["status"] == "completed"
    assert run["firewall"]["precision"] > 0.9

    history = client.get("/api/redteam/runs", headers=analyst).json()
    assert history[0]["id"] == run_id and history[0]["recall"] is not None
    assert client.get("/api/redteam/runs/nope", headers=analyst).status_code == 404

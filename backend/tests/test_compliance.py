"""Threat-coverage catalog and report."""

from fastapi.testclient import TestClient

from app.compliance.catalog import CONTROLS, FRAMEWORKS, OWASP_LLM_2025
from app.compliance.service import coverage_report
from app.main import app
from app.redteam.runner import load_agent_scenarios, load_firewall_cases
from app.redteam.service import get_redteam_service

client = TestClient(app)


def test_catalog_references_are_valid() -> None:
    control_ids = {c.id for c in CONTROLS}
    categories = {c["category"] for c in load_firewall_cases()}
    scenarios = {s["id"] for s in load_agent_scenarios()}
    for framework in FRAMEWORKS:
        for threat in framework["items"]:
            assert set(threat.controls) <= control_ids, threat.id
            for ref in threat.evidence:
                kind, _, key = ref.partition(":")
                assert (
                    (kind == "category" and key in categories)
                    or (kind == "scenario" and key in scenarios)
                    or kind == "test"
                ), (threat.id, ref)


def test_owasp_top_10_is_complete() -> None:
    assert [t.id for t in OWASP_LLM_2025] == [f"LLM{i:02d}" for i in range(1, 11)]


def test_report_before_any_run_is_unverified() -> None:
    report = coverage_report()
    assert report.evidence_run is None
    owasp = report.frameworks[0]
    assert owasp.summary["mitigated"] >= 5
    assert all(i.verified is None for i in owasp.items)


def test_report_checks_evidence_against_latest_run() -> None:
    get_redteam_service().start(["firewall", "agents"], "analyst", wait=True)
    report = coverage_report()
    assert report.evidence_run is not None
    items = {i.id: i for f in report.frameworks for i in f.items}
    assert items["LLM07"].verified is True  # prompt leakage: every category/scenario passes
    llm01 = {e.ref: e for e in items["LLM01"].evidence}
    assert llm01["AG-10"].status == "pass"
    assert llm01["obfuscation"].status == "pass"


def test_compliance_api_is_available_to_every_role() -> None:
    token = client.post(
        "/api/auth/login", data={"username": "agent", "password": "agent123"}
    ).json()["access_token"]
    resp = client.get("/api/compliance", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert {f["id"] for f in resp.json()["frameworks"]} == {"owasp-llm-2025", "mitre-atlas"}

"""Tests for the agent security scanner (audit → generate-policy → test)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.platform import cli, scanner
from app.platform.policyfile import load_aegis_file
from app.policies import config as policy_config
from app.policies import store as policy_store

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolation() -> Iterator[None]:
    """Restore the shared tool registry after scans that apply/generate policies."""
    cfg = policy_config.get_global_config()
    snapshot = [t.model_copy(deep=True) for t in cfg.tools]
    policy_store.clear_overrides()
    yield
    policy_store.clear_overrides()
    cfg.tools[:] = snapshot


def _token() -> dict[str, str]:
    resp = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ------------------------------------------------------------- discovery
def test_profile_known_agent() -> None:
    p = scanner.profile_known_agent("FinanceAgent")
    assert p.aegis_integrated and p.source == "agent"
    send = next(t for t in p.tools if t.name == "send_email")
    assert send.external and send.domain_kind == "email" and send.risk_level == "HIGH"
    kinds = {d.kind for d in p.data_sources}
    assert {"knowledge_base", "database"} <= kinds


def test_profile_directory_flags_unintegrated_agent(tmp_path) -> None:
    (tmp_path / "agent.py").write_text(
        "import openai, chromadb, requests\n"
        "def send_email(to, body): ...\n"
        "def export_data(url, data): ...\n"
        "def web_search(q): return requests.get('https://api.example.com/x')\n",
        encoding="utf-8",
    )
    p = scanner.profile_directory(tmp_path)
    assert not p.aegis_integrated and p.source == "directory"
    assert p.llm == "OpenAI"
    names = {t.name for t in p.tools}
    assert {"send_email", "export_data", "web_search"} <= names
    assert any("not behind aegisai" in n.lower() for n in p.notes)


# ------------------------------------------------------------ assessment
def test_known_agent_scores_well_and_missing_approval_is_low() -> None:
    report = scanner.audit("FinanceAgent")
    assert report.score >= 85 and report.grade in ("A", "B")
    assert len(report.findings) == 7
    approval = next(f for f in report.findings if f.category == "Missing Human Approval")
    assert approval.severity == "LOW"  # send_email already requires approval in the registry


def test_unintegrated_agent_scores_poorly(tmp_path) -> None:
    (tmp_path / "a.py").write_text(
        "import openai\n"
        "def send_email(to, body): ...\n"
        "def export_data(url, data): ...\n",
        encoding="utf-8",
    )
    report = scanner.score_report(scanner.profile_directory(tmp_path))
    assert report.score < 60 and report.grade in ("D", "F")
    sev = {f.category: f.severity for f in report.findings}
    assert sev["Prompt Injection"] == "HIGH"
    assert sev["Missing Human Approval"] == "HIGH"


# ------------------------------------------------------- policy generation
def test_generate_policy_is_least_privilege(tmp_path) -> None:
    profile = scanner.profile_known_agent("FinanceAgent")
    policy = scanner.generate_policy(profile)
    assert "send_email" in policy.approval.required_for
    assert policy.domains.allowed == ["company.com"]
    assert "customer_records" in policy.data.deny
    assert policy.trust.minimum == 0.70
    # round-trips through the loader
    out = tmp_path / "aegis.yaml"
    out.write_text(policy.to_yaml(), encoding="utf-8")
    assert load_aegis_file(out).agent.name == "FinanceAgent"


# --------------------------------------------------------------- REST
def test_api_scanner_report_and_policy() -> None:
    h = _token()
    report = client.get("/api/scanner/agents/FinanceAgent/report", headers=h)
    assert report.status_code == 200
    assert report.json()["score"] >= 85
    policy = client.get("/api/scanner/agents/FinanceAgent/policy", headers=h)
    assert "send_email" in policy.json()["aegis_yaml"]
    assert client.get("/api/scanner/agents/NoSuchAgent/report", headers=h).status_code == 404


def test_gateway_audit_endpoint() -> None:
    resp = client.post("/v1/secure/audit", json={"agent": "FinanceAgent"})
    assert resp.status_code == 200 and resp.json()["score"] >= 85


# --------------------------------------------------------------- CLI
def test_cli_audit_json(capsys) -> None:
    import json

    assert cli.main(["audit", "FinanceAgent", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["score"] >= 85


def test_cli_generate_policy_writes_file(tmp_path) -> None:
    out = tmp_path / "aegis.yaml"
    assert cli.main(["generate-policy", "FinanceAgent", "--out", str(out)]) == 0
    assert "send_email" in out.read_text(encoding="utf-8")
    assert load_aegis_file(out).approval.required_for == ["send_email"]

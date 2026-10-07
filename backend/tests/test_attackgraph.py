"""Tests for attack-surface graph, attack paths, blast radius and risk focus."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.platform import attackgraph, scanner
from app.policies import store as policy_store

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolation() -> Iterator[None]:
    yield
    policy_store.clear_overrides()


def _weak_profile(tmp_path):
    p = tmp_path / "aegis.yaml"
    p.write_text(
        "agent:\n  name: weak-agent\n"
        "permissions:\n  tools: [read_database, send_email, web_fetch]\n"
        'domains:\n  allowed: ["*"]\n'
        "data:\n  deny: [customer_records]\n",
        encoding="utf-8",
    )
    return scanner.profile_aegis_file(p)


def test_graph_has_agent_and_tool_nodes(tmp_path) -> None:
    graph = attackgraph.build_graph(_weak_profile(tmp_path))
    kinds = {n.kind for n in graph.nodes}
    assert "agent" in kinds and "tool" in kinds and "destination" in kinds
    assert any(e.source == "agent" for e in graph.edges)


def test_weak_agent_has_high_exfiltration_path(tmp_path) -> None:
    paths = attackgraph.attack_paths(_weak_profile(tmp_path))
    kinds = {p.kind for p in paths}
    assert "data_exfiltration" in kinds
    assert "indirect_injection_to_exfil" in kinds  # web_fetch is an untrusted source
    assert any(p.risk == "HIGH" for p in paths)


def test_blast_radius_is_high_for_wildcard_agent(tmp_path) -> None:
    br = attackgraph.blast_radius(_weak_profile(tmp_path))
    assert br.level == "red"
    assert br.score >= 60
    assert "ANY external host" in br.destinations
    assert "send_email" in br.dangerous_actions


def test_hardening_reduces_blast_radius(tmp_path) -> None:
    comparison = attackgraph.compare_hardening(_weak_profile(tmp_path))
    assert comparison.reduction > 0
    assert comparison.after.score < comparison.before.score


def test_risk_guided_focus_prioritises_dangerous_path(tmp_path) -> None:
    focus = attackgraph.risk_guided_focus(_weak_profile(tmp_path))
    top = min(focus, key=lambda f: f.priority)
    assert top.family in {"Indirect Injection", "Data Exfiltration"}


def test_attack_surface_api() -> None:
    token = _token()
    report = client.get("/api/attack-surface/agents/FinanceAgent", headers=token)
    assert report.status_code == 200
    body = report.json()
    assert body["agent"] == "FinanceAgent"
    assert "blast_radius" in body and "paths" in body

    blast = client.get("/api/attack-surface/agents/FinanceAgent/blast", headers=token)
    assert 0 <= blast.json()["score"] <= 100

    hardening = client.get("/api/attack-surface/agents/FinanceAgent/hardening", headers=token)
    assert hardening.json()["reduction"] >= 0


def test_attack_surface_unknown_agent_404() -> None:
    assert client.get("/api/attack-surface/agents/ghost", headers=_token()).status_code == 404


def _token(user: str = "admin", pw: str = "admin123") -> dict[str, str]:
    resp = client.post("/api/auth/login", data={"username": user, "password": pw})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}

"""Phase 13 — model provenance, the AI-BOM, and the supply-chain API."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents import brain as brain_module
from app.agents.brain import OllamaBrain, OllamaClient, RuleBasedBrain, get_brain
from app.config import get_settings
from app.database.enums import SecurityEventType
from app.main import app
from app.platform.cli import main as cli_main
from app.supply_chain import provenance
from app.supply_chain.aibom import build_aibom
from app.supply_chain.manifest import ModelManifest, get_manifest
from app.supply_chain.provenance import (
    ProvenanceError,
    check_ollama,
    clear_checks,
    recent_checks,
    verified_huggingface_path,
    verify_files,
)
from app.telemetry.store import get_audit_log

client = TestClient(app)

FILES = {"model.safetensors": b"weights", "config.json": b'{"dim": 384}'}
PINS = {name: hashlib.sha256(data).hexdigest() for name, data in FILES.items()}
REVISION = "a" * 40


@pytest.fixture(autouse=True)
def _fresh() -> Iterator[None]:
    clear_checks()
    get_brain.cache_clear()
    yield
    clear_checks()
    get_brain.cache_clear()


@pytest.fixture
def mode(monkeypatch: pytest.MonkeyPatch):
    def set_mode(value: str) -> None:
        monkeypatch.setattr(get_settings(), "model_provenance", value)

    set_mode("enforce")
    return set_mode


@pytest.fixture
def snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake Hugging Face snapshot holding FILES, and a manifest that pins them."""
    for name, data in FILES.items():
        (tmp_path / name).write_bytes(data)
    manifest = ModelManifest.model_validate(
        {
            "huggingface": [{"name": "org/model", "revision": REVISION, "files": PINS}],
            "ollama": [{"name": "llama3.1:8b", "digest": "b" * 64}],
        }
    )
    monkeypatch.setattr(provenance, "get_manifest", lambda: manifest)
    monkeypatch.setattr(provenance, "_download_snapshot", lambda *_: tmp_path)
    return tmp_path


def _anomalies() -> list:
    events = get_audit_log().list_events(limit=50)
    return [e for e in events if e.event_type == SecurityEventType.ANOMALY]


# ----------------------------------------------------------------- manifest
def test_shipped_manifest_pins_the_default_models() -> None:
    manifest = get_manifest()
    settings = get_settings()
    hf = manifest.huggingface_pin(settings.embedding_model)
    assert hf is not None and "model.safetensors" in hf.files
    assert manifest.ollama_pin(settings.model_name) is not None
    assert manifest.ollama_pin("qwen2.5:1.5b") is not None


def test_manifest_rejects_mutable_revisions_and_bad_digests() -> None:
    with pytest.raises(ValueError):
        ModelManifest.model_validate(
            {"huggingface": [{"name": "m", "revision": "main", "files": PINS}]}
        )
    with pytest.raises(ValueError):
        ModelManifest.model_validate({"ollama": [{"name": "m", "digest": "abc"}]})


def test_untagged_ollama_name_means_latest() -> None:
    manifest = ModelManifest.model_validate(
        {"ollama": [{"name": "phi3:latest", "digest": "c" * 64}]}
    )
    assert manifest.ollama_pin("phi3") is not None


# ------------------------------------------------------------ hugging face
def test_verify_files_reports_tampered_and_missing_files(snapshot: Path) -> None:
    assert verify_files(snapshot, PINS) == []
    (snapshot / "model.safetensors").write_bytes(b"backdoored")
    (snapshot / "config.json").unlink()
    problems = verify_files(snapshot, PINS)
    assert any(p.startswith("model.safetensors: sha256") for p in problems)
    assert "config.json: missing" in problems


def test_verified_snapshot_is_what_gets_loaded(mode, snapshot: Path) -> None:
    assert verified_huggingface_path("org/model") == str(snapshot)
    [check] = recent_checks()
    assert (check.status, check.allowed, check.pinned) == ("verified", True, REVISION)
    assert _anomalies() == []


def test_enforce_refuses_a_tampered_model(mode, snapshot: Path) -> None:
    (snapshot / "model.safetensors").write_bytes(b"backdoored")
    with pytest.raises(ProvenanceError, match="model.safetensors"):
        verified_huggingface_path("org/model")
    [check] = recent_checks()
    assert (check.status, check.allowed) == ("mismatch", False)
    [event] = _anomalies()
    assert event.source == "supply_chain" and event.severity.value == "HIGH"


def test_warn_mode_loads_a_tampered_model_but_records_it(mode, snapshot: Path) -> None:
    mode("warn")
    (snapshot / "model.safetensors").write_bytes(b"backdoored")
    assert verified_huggingface_path("org/model") == str(snapshot)
    assert recent_checks()[0].status == "mismatch"
    assert _anomalies()[0].severity.value == "MEDIUM"


def test_unpinned_model_is_refused_under_enforce(mode, snapshot: Path) -> None:
    with pytest.raises(ProvenanceError, match="not pinned"):
        verified_huggingface_path("someone/else")
    mode("warn")
    assert verified_huggingface_path("someone/else") == "someone/else"
    mode("off")
    assert verified_huggingface_path("someone/else") == "someone/else"
    assert recent_checks()[0].status == "skipped"


def test_unreachable_snapshot_fails_closed(
    mode, snapshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def offline(*_: object) -> Path:
        raise OSError("offline and not cached")

    monkeypatch.setattr(provenance, "_download_snapshot", offline)
    with pytest.raises(ProvenanceError, match="offline"):
        verified_huggingface_path("org/model")
    assert recent_checks()[0].status == "unavailable"


# ------------------------------------------------------------------ ollama
def test_ollama_digest_must_match_the_pin(mode, snapshot: Path) -> None:
    ok = check_ollama("llama3.1:8b", {"llama3.1:8b": "b" * 64})
    assert (ok.status, ok.allowed) == ("verified", True)
    bad = check_ollama("llama3.1:8b", {"llama3.1:8b": "f" * 64})
    assert (bad.status, bad.allowed) == ("mismatch", False)
    unknown = check_ollama("llama3.1:8b", None)
    assert (unknown.status, unknown.allowed) == ("unavailable", False)
    unpinned = check_ollama("mystery:7b", {"mystery:7b": "d" * 64})
    assert (unpinned.status, unpinned.allowed) == ("unpinned", False)


def _fake_ollama(monkeypatch: pytest.MonkeyPatch, digest: str) -> None:
    monkeypatch.setattr(get_settings(), "llm_backend", "ollama")
    monkeypatch.setattr(get_settings(), "model_name", "llama3.1:8b")
    monkeypatch.setattr(OllamaClient, "is_available", lambda self: True)
    monkeypatch.setattr(OllamaClient, "installed_digests", lambda self: {"llama3.1:8b": digest})


def test_brain_falls_back_when_the_llm_is_not_the_pinned_one(
    mode, snapshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_ollama(monkeypatch, "f" * 64)
    assert isinstance(get_brain(), RuleBasedBrain)

    get_brain.cache_clear()
    _fake_ollama(monkeypatch, "b" * 64)
    assert isinstance(brain_module.get_brain(), OllamaBrain)


# ------------------------------------------------------------------- AI-BOM
def test_aibom_lists_every_pinned_model_with_hashes() -> None:
    manifest = get_manifest()
    bom = build_aibom(manifest)
    assert bom["bomFormat"] == "CycloneDX" and bom["specVersion"] == "1.6"
    models = [c for c in bom["components"] if c["type"] == "machine-learning-model"]
    assert len(models) == len(manifest.huggingface) + len(manifest.ollama)
    hf = models[0]
    assert hf["purl"].startswith("pkg:huggingface/sentence-transformers/all-minilm-l6-v2@")
    assert {f["name"] for f in hf["components"]} == set(manifest.huggingface[0].files)
    assert all(m["hashes"] for m in models)
    # Reproducible: the same manifest gives the same serial number.
    assert build_aibom(manifest)["serialNumber"] == bom["serialNumber"]


def test_cli_writes_the_aibom(tmp_path: Path) -> None:
    out = tmp_path / "models.cdx.json"
    assert cli_main(["aibom", "-o", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["bomFormat"] == "CycloneDX"


# --------------------------------------------------------------------- API
def test_supply_chain_api(mode, snapshot: Path) -> None:
    token = client.post(
        "/api/auth/login", data={"username": "analyst", "password": "analyst123"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    verified_huggingface_path("org/model")

    report = client.get("/api/supply-chain", headers=headers)
    assert report.status_code == 200
    body = report.json()
    assert body["mode"] == "enforce"
    assert body["checks"][0]["status"] == "verified"
    assert client.get("/api/supply-chain/aibom", headers=headers).json()["specVersion"] == "1.6"
    assert client.get("/api/supply-chain").status_code == 401

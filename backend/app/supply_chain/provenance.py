"""Model provenance checks (Phase 13, OWASP LLM03).

Before a model is used it is matched against its pin in the model manifest:

* **Hugging Face** — the repository is fetched at the pinned commit, only the
  pinned files are downloaded, and each is hashed and compared *before* the
  model is loaded from that verified local copy (so what was checked is what
  runs).
* **Ollama** — the digest of the installed model must equal the pinned one.

``MODEL_PROVENANCE`` decides what a failed check does: ``enforce`` refuses the
model, ``warn`` uses it anyway; both record an ANOMALY security event. Every
check's outcome is kept for the supply-chain report.
"""

from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import structlog
from pydantic import BaseModel, Field

from app.config import get_settings
from app.database.enums import SecurityEventType, SecuritySeverity
from app.supply_chain.manifest import get_manifest, ollama_name
from app.telemetry.store import get_audit_log

logger = structlog.get_logger("aegisai.supply_chain")

CheckStatus = Literal["verified", "mismatch", "unpinned", "unavailable", "skipped"]


class ProvenanceError(RuntimeError):
    """A model failed its provenance check while MODEL_PROVENANCE=enforce."""


class ModelCheck(BaseModel):
    kind: Literal["huggingface", "ollama"]
    name: str
    status: CheckStatus
    allowed: bool
    pinned: str | None = None  # revision or digest
    observed: str | None = None
    detail: str
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


_checks: dict[tuple[str, str], ModelCheck] = {}
_lock = threading.Lock()


def provenance_mode() -> str:
    mode = get_settings().model_provenance.lower()
    return mode if mode in {"enforce", "warn", "off"} else "enforce"


def recent_checks() -> list[ModelCheck]:
    with _lock:
        return sorted(_checks.values(), key=lambda c: (c.kind, c.name))


def clear_checks() -> None:
    with _lock:
        _checks.clear()


def _record(check: ModelCheck) -> ModelCheck:
    with _lock:
        _checks[(check.kind, check.name)] = check
    if check.status in {"mismatch", "unpinned"}:
        get_audit_log().record_event(
            event_type=SecurityEventType.ANOMALY,
            severity=SecuritySeverity.HIGH if not check.allowed else SecuritySeverity.MEDIUM,
            source="supply_chain",
            description=f"Model provenance {check.status}: {check.name}. {check.detail}",
            details=check.model_dump(mode="json", exclude={"checked_at"}),
        )
    else:
        logger.info("model_provenance", **check.model_dump(mode="json"))
    return check


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_files(root: Path, files: dict[str, str]) -> list[str]:
    """Problems found comparing ``root``'s files with their pinned SHA-256 (empty = all match)."""
    problems: list[str] = []
    for rel, expected in sorted(files.items()):
        path = root / rel
        if not path.is_file():
            problems.append(f"{rel}: missing")
            continue
        actual = sha256_file(path)
        if actual != expected:
            problems.append(f"{rel}: sha256 {actual[:12]}… ≠ pinned {expected[:12]}…")
    return problems


def _download_snapshot(repo_id: str, revision: str, files: list[str]) -> Path:
    from huggingface_hub import snapshot_download

    return Path(snapshot_download(repo_id=repo_id, revision=revision, allow_patterns=files))


def verified_huggingface_path(name: str) -> str:
    """Where to load Hugging Face model ``name`` from, after checking its provenance.

    Returns the verified local snapshot, or ``name`` itself when the check is off
    (or the model is unpinned and only warned about). Raises
    :class:`ProvenanceError` when MODEL_PROVENANCE=enforce and the check fails.
    """
    mode = provenance_mode()
    if mode == "off":
        _record(
            ModelCheck(
                kind="huggingface",
                name=name,
                status="skipped",
                allowed=True,
                detail="MODEL_PROVENANCE=off",
            )
        )
        return name
    pin = get_manifest().huggingface_pin(name)
    if pin is None:
        check = _record(
            ModelCheck(
                kind="huggingface",
                name=name,
                status="unpinned",
                allowed=mode == "warn",
                detail="Not listed in the model manifest.",
            )
        )
        if not check.allowed:
            raise ProvenanceError(f"{name} is not pinned in the model manifest.")
        return name

    try:
        root = _download_snapshot(pin.name, pin.revision, list(pin.files))
    except Exception as exc:  # offline and not cached, hub error, …
        check = _record(
            ModelCheck(
                kind="huggingface",
                name=name,
                status="unavailable",
                allowed=mode == "warn",
                pinned=pin.revision,
                detail=f"Could not fetch the pinned snapshot: {exc}",
            )
        )
        if not check.allowed:
            raise ProvenanceError(f"{name}: {check.detail}") from exc
        return name
    problems = verify_files(root, pin.files)
    check = _record(
        ModelCheck(
            kind="huggingface",
            name=name,
            status="mismatch" if problems else "verified",
            allowed=not problems or mode == "warn",
            pinned=pin.revision,
            observed=pin.revision if not problems else None,
            detail="; ".join(problems)
            if problems
            else f"{len(pin.files)} file(s) match their SHA-256 pins.",
        )
    )
    if not check.allowed:
        raise ProvenanceError(f"{name} failed its provenance check: {check.detail}")
    return str(root)


def check_ollama(name: str, installed: dict[str, str] | None) -> ModelCheck:
    """Check Ollama model ``name`` against its pin.

    ``installed`` maps each installed model name to its digest (from
    ``/api/tags``), or is ``None`` when the server could not be asked.
    """
    mode = provenance_mode()
    if mode == "off":
        return _record(
            ModelCheck(
                kind="ollama",
                name=name,
                status="skipped",
                allowed=True,
                detail="MODEL_PROVENANCE=off",
            )
        )
    pin = get_manifest().ollama_pin(name)
    observed = None if installed is None else installed.get(ollama_name(name))
    if pin is None:
        return _record(
            ModelCheck(
                kind="ollama",
                name=name,
                status="unpinned",
                allowed=mode == "warn",
                observed=observed,
                detail="Not listed in the model manifest.",
            )
        )
    if observed is None:
        return _record(
            ModelCheck(
                kind="ollama",
                name=name,
                status="unavailable",
                allowed=mode == "warn",
                pinned=pin.digest,
                detail="Could not read the installed model's digest from Ollama.",
            )
        )
    observed = observed.removeprefix("sha256:").lower()
    ok = observed == pin.digest
    return _record(
        ModelCheck(
            kind="ollama",
            name=name,
            status="verified" if ok else "mismatch",
            allowed=ok or mode == "warn",
            pinned=pin.digest,
            observed=observed,
            detail="Installed digest matches the pin."
            if ok
            else f"Installed digest {observed[:12]} ≠ pinned {pin.digest[:12]}.",
        )
    )

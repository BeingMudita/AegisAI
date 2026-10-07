"""AI bill of materials — the pinned models as a CycloneDX 1.6 SBOM.

Package SBOMs (``cyclonedx-py`` / ``cyclonedx-npm`` in CI) list the code; this
lists the *models*, as ``machine-learning-model`` components carrying the
pinned commit or digest and the SHA-256 of every pinned file, so the models
can be inventoried and diffed with the same tools as the packages.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app import __version__
from app.supply_chain.manifest import HuggingFacePin, ModelManifest, OllamaPin

_NAMESPACE = uuid.UUID("6f1c2a52-6a0e-4b8e-9a43-2d1f0c7e5b10")


def _license(value: str | None) -> list[dict[str, Any]]:
    if not value:
        return []
    key = "name" if value.startswith("LicenseRef-") else "id"
    return [{"license": {key: value}}]


def _huggingface(pin: HuggingFacePin) -> dict[str, Any]:
    group, _, name = pin.name.rpartition("/")
    ref = f"pkg:huggingface/{pin.name.lower()}@{pin.revision}"
    weights = [d for f, d in pin.files.items() if f.endswith((".safetensors", ".bin"))]
    return {
        "type": "machine-learning-model",
        "bom-ref": ref,
        "group": group or None,
        "name": name,
        "version": pin.revision,
        "purl": ref,
        "description": pin.purpose,
        "licenses": _license(pin.license),
        "hashes": [{"alg": "SHA-256", "content": d} for d in weights],
        "externalReferences": [
            {
                "type": "distribution",
                "url": f"https://huggingface.co/{pin.name}/tree/{pin.revision}",
            }
        ],
        "components": [
            {
                "type": "file",
                "bom-ref": f"{ref}#{path}",
                "name": path,
                "hashes": [{"alg": "SHA-256", "content": digest}],
            }
            for path, digest in sorted(pin.files.items())
        ],
    }


def _ollama(pin: OllamaPin) -> dict[str, Any]:
    name, _, tag = pin.name.partition(":")
    hashes = [{"alg": "SHA-256", "content": pin.weights}] if pin.weights else []
    return {
        "type": "machine-learning-model",
        "bom-ref": f"ollama:{pin.name}@sha256:{pin.digest}",
        "name": name,
        "version": tag or "latest",
        "description": pin.purpose,
        "licenses": _license(pin.license),
        "hashes": hashes,
        "properties": [{"name": "ollama:manifest-digest", "value": f"sha256:{pin.digest}"}],
        "externalReferences": [
            {"type": "distribution", "url": f"https://ollama.com/library/{pin.name}"}
        ],
    }


def _prune(value: Any) -> Any:
    """Drop empty fields so the document validates (CycloneDX rejects nulls)."""
    if isinstance(value, dict):
        return {k: _prune(v) for k, v in value.items() if v not in (None, [], {})}
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


def build_aibom(manifest: ModelManifest, *, timestamp: datetime | None = None) -> dict[str, Any]:
    components = [_huggingface(p) for p in manifest.huggingface]
    components += [_ollama(p) for p in manifest.ollama]
    # Same manifest → same serial number, so the file is reproducible and diffable.
    serial = uuid.uuid5(_NAMESPACE, json.dumps(components, sort_keys=True))
    when = (timestamp or datetime.now(timezone.utc)).replace(microsecond=0)
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "timestamp": when.isoformat().replace("+00:00", "Z"),
            "tools": {"components": [{"type": "application", "name": "aegis aibom"}]},
            "component": {
                "type": "application",
                "bom-ref": "aegisai",
                "name": "aegisai",
                "version": __version__,
            },
        },
        "components": components,
        "dependencies": [
            {"ref": "aegisai", "dependsOn": [c["bom-ref"] for c in components]},
        ],
    }
    return _prune(bom)

"""Training data and fingerprints for the semantic layer.

Two kinds of training data, kept apart on purpose:

* **real development sets** (``firewall_cases.yaml``, ``firewall_paraphrase.yaml``) —
  these alone define recall / FPR and the decision threshold;
* **adversarial augmentation** (``adversarial.py``) — synthetic variants that join
  every training fold to teach the weights, but are never evaluated.

The held-out files are never read here. A fingerprint of the parsed cases (not
the file bytes, so line endings don't matter) plus the augmentation's own
fingerprint is stored in the model, so a stale model — from an edit to either —
is detectable.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.firewall import adversarial
from app.firewall.scanner import PromptFirewall
from app.firewall.schemas import ContentChannel, FirewallAction
from app.firewall.semantic import Example
from app.redteam import runner

TRAINING_SETS: dict[str, Any] = {
    "firewall_cases.yaml": runner.load_firewall_cases,
    "firewall_paraphrase.yaml": runner.load_paraphrase_cases,
}

#: Fingerprint key for the adversarial augmentation (not a file, so it can't
#: collide with a YAML set name).
AUGMENTATION_KEY = "adversarial_augmentation"


def _fingerprint(cases: list[dict[str, Any]]) -> str:
    canonical = [
        {k: c[k] for k in ("id", "channel", "malicious", "text")}
        for c in sorted(cases, key=lambda c: c["id"])
    ]
    blob = json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def training_sets() -> dict[str, list[dict[str, Any]]]:
    return {name: load() for name, load in TRAINING_SETS.items()}


def fingerprints(sets: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, str]:
    sets = sets if sets is not None else training_sets()
    prints = {name: _fingerprint(cases) for name, cases in sets.items()}
    prints[AUGMENTATION_KEY] = adversarial.fingerprint()
    return prints


def rule_detections(data: list[Example]) -> list[bool]:
    """Whether the signature rules alone flag each example."""
    rules_only = PromptFirewall(semantic=None)
    return [
        rules_only.scan(e.text, ContentChannel(e.channel)).action != FirewallAction.ALLOW
        for e in data
    ]


def examples(sets: dict[str, list[dict[str, Any]]] | None = None) -> list[Example]:
    """The real development examples — the set recall and the threshold are measured on."""
    sets = sets if sets is not None else training_sets()
    return [
        Example(text=c["text"], channel=c["channel"], malicious=bool(c["malicious"]))
        for cases in sets.values()
        for c in cases
    ]


def augmented_examples() -> list[Example]:
    """Synthetic adversarial examples — added to training folds, never evaluated."""
    return adversarial.generate()

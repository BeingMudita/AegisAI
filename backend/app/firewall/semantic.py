"""The firewall's semantic layer — a learned prompt-injection classifier (Phase 12).

Signature rules catch attacks that use known trigger phrases and miss the same
intent in other words. This layer is an L2-regularised logistic regression over
hashed features of the normalised text:

* stemmed word unigrams and bigrams — the vocabulary of an attack ("guidance …
  no longer applies", "persona … no filters"), not one exact phrase;
* the channel the text arrived on (instructions in a retrieved document mean
  more than the same words typed by the user).

(Character n-grams were tried and dropped: on this much data they lowered
cross-validated recall at the same false-positive rate.)

It is trained offline on the development sets only (``firewall_cases.yaml`` and
``firewall_paraphrase.yaml``) by ``evaluation/train_semantic.py``; the decision
threshold comes from cross-validation on that data, never from the held-out
sets. The weights ship as ``semantic_model.json`` with the SHA-256 of the data
they were trained on, so CI can tell when the model is stale.

The scanner consults it only for text the rules let through, and a semantic hit
can raise ALLOW to FLAG — never to BLOCK — so a false positive costs a review,
not a refusal. Pure Python with no dependencies: it runs wherever the API does.
"""

from __future__ import annotations

import json
import math
import random
import re
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.firewall.normalize import normalize

MODEL_PATH = Path(__file__).with_name("semantic_model.json")
FEATURE_VERSION = 1
HASH_BITS = 18
_MASK = (1 << HASH_BITS) - 1
_WORD = re.compile(r"[a-z0-9]+")
_SUFFIXES = ("ing", "ied", "ies", "ed", "es", "ly", "s")
_MAX_CHARS = 8000  # longer text is scored on its first 8,000 characters


def _stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _hash(feature: str) -> int:
    return zlib.crc32(feature.encode("utf-8")) & _MASK


def features(text: str, channel: str, *, canonical: bool = False) -> dict[int, float]:
    """Hashed, binary, L2-normalised features of ``text`` arriving on ``channel``.

    ``canonical=True`` means ``text`` was already normalised (the scanner's copy).
    """
    clipped = text[:_MAX_CHARS]
    canonical_text = (clipped if canonical else normalize(clipped).text).lower()
    words = _WORD.findall(canonical_text)
    stems = [_stem(w) for w in words]
    names = {f"c:{channel}"}
    names.update(f"w:{s}" for s in stems)
    names.update(f"b:{a}_{b}" for a, b in zip(stems, stems[1:], strict=False))
    indices = {_hash(n) for n in names}
    value = 1.0 / math.sqrt(len(indices))
    return dict.fromkeys(indices, value)


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


@dataclass
class Example:
    text: str
    channel: str
    malicious: bool


@dataclass
class LogisticModel:
    bias: float = 0.0
    weights: dict[int, float] = field(default_factory=dict)

    def probability(self, x: dict[int, float]) -> float:
        z = self.bias + sum(self.weights.get(i, 0.0) * v for i, v in x.items())
        return _sigmoid(z)


def train(
    examples: Sequence[Example], *, l2: float = 1e-3, epochs: int = 40, seed: int = 7
) -> LogisticModel:
    """Class-balanced logistic regression by AdaGrad SGD — deterministic for a seed."""
    data = [(features(e.text, e.channel), 1.0 if e.malicious else 0.0) for e in examples]
    positives = sum(y for _, y in data) or 1.0
    negatives = (len(data) - positives) or 1.0
    class_weight = {1.0: len(data) / (2 * positives), 0.0: len(data) / (2 * negatives)}
    model = LogisticModel()
    grad_sq: dict[int, float] = {}
    bias_sq = 0.0
    rate = 0.5
    order = list(range(len(data)))
    rng = random.Random(seed)
    for _ in range(epochs):
        rng.shuffle(order)
        for k in order:
            x, y = data[k]
            err = (model.probability(x) - y) * class_weight[y]
            for i, v in x.items():
                w = model.weights.get(i, 0.0)
                g = err * v + l2 * w
                grad_sq[i] = grad_sq.get(i, 0.0) + g * g
                model.weights[i] = w - rate * g / math.sqrt(grad_sq[i])
            bias_sq += err * err
            model.bias -= rate * err / math.sqrt(bias_sq)
    return model


def out_of_fold_probabilities(
    examples: Sequence[Example], *, folds: int = 5, **kwargs: Any
) -> list[float]:
    """Each example's probability from a model trained without it (stratified k-fold)."""
    by_class: dict[bool, list[int]] = {True: [], False: []}
    for i, e in enumerate(examples):
        by_class[e.malicious].append(i)
    fold_of = {}
    for indices in by_class.values():
        for rank, i in enumerate(indices):
            fold_of[i] = rank % folds
    probs = [0.0] * len(examples)
    for f in range(folds):
        train_set = [e for i, e in enumerate(examples) if fold_of[i] != f]
        model = train(train_set, **kwargs)
        for i, e in enumerate(examples):
            if fold_of[i] == f:
                probs[i] = model.probability(features(e.text, e.channel))
    return probs


def pick_threshold(
    examples: Sequence[Example],
    probs: Sequence[float],
    rules_detected: Sequence[bool],
    *,
    max_fpr: float,
) -> tuple[float, dict[str, float]]:
    """The threshold that maximises the recall of rules-OR-semantic while its
    false-positive rate stays within ``max_fpr`` (ties: the higher threshold).

    ``probs`` should be out-of-fold, so the metrics estimate unseen text.
    """
    attacks = [i for i, e in enumerate(examples) if e.malicious]
    benign = [i for i, e in enumerate(examples) if not e.malicious]
    best: tuple[float, float, float] | None = None  # (recall, threshold, fpr)
    for step in range(99, 49, -1):
        t = step / 100
        hit = [rules_detected[i] or probs[i] >= t for i in range(len(examples))]
        fpr = sum(hit[i] for i in benign) / len(benign) if benign else 0.0
        recall = sum(hit[i] for i in attacks) / len(attacks) if attacks else 0.0
        if fpr <= max_fpr and (best is None or recall > best[0]):
            best = (recall, t, fpr)
    if best is None:  # the rules alone exceed the budget: semantic adds nothing
        return 0.99, {"cv_recall": 0.0, "cv_false_positive_rate": 0.0}
    recall, threshold, fpr = best
    rules_recall = sum(rules_detected[i] for i in attacks) / len(attacks) if attacks else 0.0
    return threshold, {
        "cv_recall": round(recall, 4),
        "cv_false_positive_rate": round(fpr, 4),
        "rules_only_recall": round(rules_recall, 4),
    }


class SemanticClassifier:
    """The shipped model: probability that a text is an injection attempt."""

    def __init__(self, model: LogisticModel, threshold: float, meta: dict[str, Any]) -> None:
        self.model = model
        self.threshold = threshold
        self.meta = meta

    def probability(self, text: str, channel: str, *, canonical: bool = False) -> float:
        return self.model.probability(features(text, channel, canonical=canonical))

    def to_json(self) -> dict[str, Any]:
        return {
            "feature_version": FEATURE_VERSION,
            "hash_bits": HASH_BITS,
            "threshold": self.threshold,
            "bias": round(self.model.bias, 6),
            "weights": {
                str(i): round(w, 6) for i, w in sorted(self.model.weights.items()) if abs(w) >= 1e-6
            },
            **self.meta,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> SemanticClassifier:
        if data.get("feature_version") != FEATURE_VERSION or data.get("hash_bits") != HASH_BITS:
            raise ValueError("semantic_model.json was built with different features; retrain it.")
        model = LogisticModel(
            bias=float(data["bias"]),
            weights={int(i): float(w) for i, w in data["weights"].items()},
        )
        meta = {
            k: v
            for k, v in data.items()
            if k not in {"feature_version", "hash_bits", "threshold", "bias", "weights"}
        }
        return cls(model, float(data["threshold"]), meta)

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> SemanticClassifier:
        return cls.from_json(json.loads(path.read_text(encoding="utf-8")))


@lru_cache
def get_semantic_classifier() -> SemanticClassifier | None:
    """The shipped classifier, or None when FIREWALL_SEMANTIC is off or no model exists."""
    if not get_settings().firewall_semantic or not MODEL_PATH.exists():
        return None
    return SemanticClassifier.load()

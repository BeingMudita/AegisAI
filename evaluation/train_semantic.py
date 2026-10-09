"""Train the firewall's semantic layer (Phase 12) and write ``semantic_model.json``.

Training data: the development sets only — ``firewall_cases.yaml`` and
``firewall_paraphrase.yaml``. The held-out sets are never read.

1. Pick the L2 strength by 5-fold stratified cross-validation: the one whose
   out-of-fold probabilities give the firewall (rules OR semantic) the best
   recall at a false-positive rate of at most ``--max-fpr``.
2. That search also sets the decision threshold.
3. Train on all the development data and write the weights, the threshold, the
   cross-validation metrics and a fingerprint of the training data.

Deterministic: the same data gives the same model.

    backend/.venv/Scripts/python evaluation/train_semantic.py          # retrain
    backend/.venv/Scripts/python evaluation/train_semantic.py --check  # stale?
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.firewall import semantic  # noqa: E402
from app.firewall.semantic_training import (  # noqa: E402
    examples,
    fingerprints,
    rule_detections,
    training_sets,
)

L2_GRID = (1e-4, 3e-4, 1e-3, 3e-3)
EPOCHS = 40
SEED = 7


def check() -> int:
    if not semantic.MODEL_PATH.exists():
        print("No semantic_model.json; run evaluation/train_semantic.py.", file=sys.stderr)
        return 1
    shipped = json.loads(semantic.MODEL_PATH.read_text(encoding="utf-8"))
    if shipped.get("trained_on") != fingerprints():
        print("semantic_model.json is stale: the training data changed. Retrain.", file=sys.stderr)
        return 1
    print("semantic_model.json matches the training data.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only verify the model is current")
    parser.add_argument("--max-fpr", type=float, default=0.05)
    args = parser.parse_args()
    if args.check:
        return check()

    sets = training_sets()
    data = examples(sets)
    rules = rule_detections(data)
    print(f"Training on {len(data)} development cases ({sum(e.malicious for e in data)} attacks)")

    best = None
    for l2 in L2_GRID:
        probs = semantic.out_of_fold_probabilities(data, l2=l2, epochs=EPOCHS, seed=SEED)
        threshold, cv = semantic.pick_threshold(data, probs, rules, max_fpr=args.max_fpr)
        print(f"  l2={l2:g}: threshold {threshold:.3f}, out-of-fold {cv}")
        if best is None or cv["cv_recall"] > best[2]["cv_recall"]:  # ties: weaker l2 wins
            best = (l2, threshold, cv)
    assert best is not None
    l2, threshold, cv = best

    model = semantic.train(data, l2=l2, epochs=EPOCHS, seed=SEED)
    classifier = semantic.SemanticClassifier(
        model,
        threshold,
        {
            "trained_on": fingerprints(sets),
            "training_cases": len(data),
            "hyperparameters": {"l2": l2, "epochs": EPOCHS, "seed": SEED, "folds": 5},
            "threshold_rule": (
                f"best rules-OR-semantic recall at out-of-fold FPR <= {args.max_fpr:.0%}"
            ),
            "cross_validation": cv,
        },
    )
    semantic.MODEL_PATH.write_text(
        json.dumps(classifier.to_json(), indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote {semantic.MODEL_PATH.relative_to(ROOT)}: l2={l2:g}, threshold {threshold:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

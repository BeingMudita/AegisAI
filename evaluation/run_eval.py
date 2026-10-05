"""AegisAI evaluation harness (command line).

Runs the two red-team suites in ``attack-scenarios/`` against the backend
in-process and writes a report:

* **Firewall benchmark** — labelled malicious / benign texts → detection
  precision, recall, F1, false-positive rate, per-category rates, latency.
* **Agent scenarios** — full guarded agent turns (deterministic rule-based
  brain, fresh isolated runtime per scenario) checked against expected
  outcomes: what was blocked, which tools ran, were refused (and where) or
  wait for human approval, and what must never appear in the answer.

The suites themselves live in ``backend/app/redteam/runner.py`` — the same code
the dashboard's Red-team lab runs.

Usage (from the repo root, with the backend's virtualenv)::

    backend/.venv/Scripts/python evaluation/run_eval.py          # Windows
    backend/.venv/bin/python evaluation/run_eval.py              # macOS / Linux

Exits non-zero if any agent scenario fails, so it can gate CI.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# Deterministic, offline backends — set before the app reads its settings.
os.environ.setdefault("LLM_BACKEND", "rule_based")
os.environ.setdefault("EMBEDDING_BACKEND", "hashing")

from app.config import get_settings  # noqa: E402
from app.redteam import runner  # noqa: E402
from app.telemetry.logging import configure_logging  # noqa: E402
from app.telemetry.store import isolated_audit_log  # noqa: E402

fresh_runtime = runner.fresh_runtime


def run_firewall_benchmark(cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    with isolated_audit_log():
        return runner.run_firewall_benchmark(cases).model_dump(mode="json")


def run_agent_scenarios(scenarios: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    with isolated_audit_log():
        return runner.run_agent_scenarios(scenarios).model_dump(mode="json")


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
def render_markdown(fw: dict[str, Any], ag: dict[str, Any]) -> str:
    c = fw["confusion"]
    lines = [
        "# AegisAI evaluation report",
        "",
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · "
        f"firewall thresholds: flag {get_settings().firewall_flag_threshold}, "
        f"block {get_settings().firewall_block_threshold} · agent brain: rule_based_",
        "",
        "## Firewall benchmark",
        "",
        f"{fw['cases']} labelled inputs ({fw['malicious']} malicious, {fw['benign']} benign). "
        "*Detected* means FLAG or BLOCK.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Precision | {fw['precision']:.1%} |",
        f"| Recall (detection rate) | {fw['recall']:.1%} |",
        f"| F1 | {fw['f1']:.3f} |",
        f"| False-positive rate | {fw['false_positive_rate']:.1%} |",
        f"| Malicious inputs blocked outright | {fw['block_rate_malicious']:.1%} |",
        f"| Benign inputs blocked outright | {fw['block_rate_benign']:.1%} |",
        f"| Latency p50 / p95 / max | {fw['latency_ms']['p50']} / {fw['latency_ms']['p95']} / "
        f"{fw['latency_ms']['max']} ms |",
        "",
        f"Confusion matrix: TP {c['tp']} · FN {c['fn']} · FP {c['fp']} · TN {c['tn']}",
        "",
        "### Detection by category",
        "",
        "| Category | Cases | Detected | Blocked | Detection rate |",
        "|---|---|---|---|---|",
    ]
    for v in fw["by_category"]:
        lines.append(
            f"| {v['category']} | {v['n']} | {v['detected']} | {v['blocked']} | "
            f"{v['detection_rate']:.0%} |"
        )

    def _rows(title: str, rows: list[dict[str, Any]]) -> None:
        lines.extend(["", f"### {title}", ""])
        if not rows:
            lines.append("None.")
            return
        lines.extend(["| Case | Channel | Action | Score | Text |", "|---|---|---|---|---|"])
        for r in rows:
            text = r["text"].replace("|", "\\|").replace("\n", " ")
            text = text if len(text) <= 90 else text[:89] + "…"
            lines.append(
                f"| {r['id']} | {r['channel']} | {r['action']} | {r['score']:.2f} | {text} |"
            )

    _rows("Missed attacks (false negatives)", fw["misses"])
    _rows("False positives", fw["false_positives"])

    lines += [
        "",
        "## Agent scenarios",
        "",
        f"**{ag['passed']} / {ag['scenarios']} passed** ({ag['pass_rate']:.0%}).",
        "",
        "| Scenario | Result | Blocked | Tool calls | Notes |",
        "|---|---|---|---|---|",
    ]
    for r in ag["results"]:
        lines.append(
            f"| {r['id']} {r['title']} | {'PASS' if r['passed'] else 'FAIL'} | "
            f"{'yes' if r['blocked'] else 'no'} | {', '.join(r['tools']) or '—'} | "
            f"{'; '.join(r['failures'])} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=ROOT / "evaluation" / "results")
    args = parser.parse_args(argv)

    configure_logging("CRITICAL")
    fw = run_firewall_benchmark()
    ag = run_agent_scenarios()

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(
        json.dumps({"firewall": fw, "agents": ag}, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (args.out / "report.md").write_text(render_markdown(fw, ag), encoding="utf-8")

    print(
        f"Firewall: precision {fw['precision']:.1%}, recall {fw['recall']:.1%}, "
        f"FPR {fw['false_positive_rate']:.1%}, p95 {fw['latency_ms']['p95']} ms"
    )
    print(f"Agents:   {ag['passed']}/{ag['scenarios']} scenarios passed")
    for r in ag["results"]:
        if not r["passed"]:
            print(f"  FAIL {r['id']}: {'; '.join(r['failures'])}")
    print(f"Report:   {args.out / 'report.md'}")
    return 0 if ag["passed"] == ag["scenarios"] else 1


if __name__ == "__main__":
    sys.exit(main())

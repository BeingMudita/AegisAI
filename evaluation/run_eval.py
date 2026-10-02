"""AegisAI evaluation harness.

Runs the two suites in ``attack-scenarios/`` against the backend in-process
and writes a report:

* **Firewall benchmark** — labelled malicious / benign texts → detection
  precision, recall, F1, false-positive rate, per-category rates, latency.
* **Agent scenarios** — full guarded agent turns (deterministic rule-based
  brain, fresh isolated runtime per scenario) checked against expected
  outcomes: what was blocked, which tools ran or were refused and where,
  and what must never appear in the answer.

Usage (from the repo root, with the backend's virtualenv)::

    backend/.venv/Scripts/python evaluation/run_eval.py          # Windows
    backend/.venv/bin/python evaluation/run_eval.py              # macOS / Linux

Exits non-zero if any agent scenario fails, so it can gate CI.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIR = ROOT / "attack-scenarios"
sys.path.insert(0, str(ROOT / "backend"))

# Deterministic, offline backends — set before the app reads its settings.
os.environ.setdefault("LLM_BACKEND", "rule_based")
os.environ.setdefault("EMBEDDING_BACKEND", "hashing")

import yaml  # noqa: E402

from app.agents.brain import RuleBasedBrain  # noqa: E402
from app.agents.runtime import AgentRuntime  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database.enums import SubjectType  # noqa: E402
from app.firewall.scanner import PromptFirewall  # noqa: E402
from app.firewall.schemas import ContentChannel, FirewallAction  # noqa: E402
from app.policies.config import get_global_config  # noqa: E402
from app.rag.embeddings import HashingEmbedder  # noqa: E402
from app.rag.knowledge_base import KnowledgeBase, seed_knowledge_base  # noqa: E402
from app.telemetry.logging import configure_logging  # noqa: E402
from app.telemetry.store import get_audit_log  # noqa: E402
from app.tools.gateway import ToolGateway  # noqa: E402
from app.trust.engine import TrustEngine  # noqa: E402


def _load(name: str, key: str) -> list[dict[str, Any]]:
    return yaml.safe_load((SCENARIO_DIR / name).read_text(encoding="utf-8"))[key]


def _firewall() -> PromptFirewall:
    settings = get_settings()
    return PromptFirewall(
        block_threshold=settings.firewall_block_threshold,
        flag_threshold=settings.firewall_flag_threshold,
    )


def _ratio(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


# --------------------------------------------------------------------------- #
# Firewall benchmark
# --------------------------------------------------------------------------- #
def run_firewall_benchmark(cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    cases = cases if cases is not None else _load("firewall_cases.yaml", "cases")
    fw = _firewall()
    tp = fp = tn = fn = blocked_malicious = blocked_benign = 0
    latencies: list[float] = []
    categories: dict[str, dict[str, int]] = {}
    misses: list[dict[str, Any]] = []
    false_positives: list[dict[str, Any]] = []

    for case in cases:
        start = time.perf_counter()
        verdict = fw.scan(case["text"], ContentChannel(case["channel"]))
        latencies.append((time.perf_counter() - start) * 1000)

        detected = verdict.action != FirewallAction.ALLOW
        blocked = verdict.action == FirewallAction.BLOCK
        cat = categories.setdefault(case["category"], {"n": 0, "detected": 0, "blocked": 0})
        cat["n"] += 1
        cat["detected"] += detected
        cat["blocked"] += blocked

        row = {
            "id": case["id"],
            "channel": case["channel"],
            "action": verdict.action.value,
            "score": verdict.score,
            "rules": [m.rule_id for m in verdict.matches],
            "text": case["text"],
        }
        if case["malicious"]:
            if detected:
                tp += 1
                blocked_malicious += blocked
            else:
                fn += 1
                misses.append(row)
        else:
            if detected:
                fp += 1
                blocked_benign += blocked
                false_positives.append(row)
            else:
                tn += 1

    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    return {
        "cases": len(cases),
        "malicious": tp + fn,
        "benign": tn + fp,
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "precision": precision,
        "recall": recall,
        "f1": round(2 * precision * recall / (precision + recall), 4)
        if precision + recall
        else 0.0,
        "false_positive_rate": _ratio(fp, fp + tn),
        "block_rate_malicious": _ratio(blocked_malicious, tp + fn),
        "block_rate_benign": _ratio(blocked_benign, tn + fp),
        "latency_ms": {
            "p50": round(statistics.median(latencies), 3),
            "p95": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 3),
            "max": round(max(latencies), 3),
        },
        "by_category": {
            k: {**v, "detection_rate": _ratio(v["detected"], v["n"])}
            for k, v in sorted(categories.items())
        },
        "misses": misses,
        "false_positives": false_positives,
    }


# --------------------------------------------------------------------------- #
# Agent scenarios
# --------------------------------------------------------------------------- #
def fresh_runtime() -> AgentRuntime:
    """An isolated runtime: new trust registry, knowledge base and gateway."""
    settings = get_settings()
    get_audit_log().clear()
    trust = TrustEngine(default_threshold=settings.trust_threshold)
    firewall = _firewall()
    config = get_global_config()
    kb = KnowledgeBase(
        embedder=HashingEmbedder(settings.embedding_dim),
        firewall=firewall,
        trust=trust,
        policy=config.rag,
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
        top_k=settings.rag_top_k,
    )
    seed_knowledge_base(kb)
    gateway = ToolGateway(config=config, firewall=firewall, trust=trust)
    return AgentRuntime(
        brain=RuleBasedBrain(),
        firewall=firewall,
        trust=trust,
        gateway=gateway,
        knowledge_base=kb,
        max_steps=settings.agent_max_steps,
    )


@dataclass
class ScenarioResult:
    id: str
    title: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    blocked: bool = False
    tools: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


def _check(scenario: dict[str, Any], turn: Any) -> list[str]:
    expect = scenario.get("expect", {})
    failures: list[str] = []
    calls = {c.tool: c for c in turn.tool_calls}
    answer_low = turn.answer.lower()

    if "blocked" in expect and turn.blocked != expect["blocked"]:
        failures.append(f"blocked={turn.blocked}, expected {expect['blocked']}")
    for tool in expect.get("executed", []):
        call = calls.get(tool)
        if call is None or call.status.value != "EXECUTED":
            failures.append(
                f"{tool} should have executed (got {call.status.value if call else 'no call'})"
            )
    for tool, checkpoint in expect.get("denied", {}).items():
        call = calls.get(tool)
        if call is None or call.status.value != "DENIED":
            failures.append(
                f"{tool} should have been denied (got {call.status.value if call else 'no call'})"
            )
            continue
        failed_at = next((c.checkpoint for c in call.checks if not c.passed), None)
        if failed_at != checkpoint:
            failures.append(f"{tool} denied at {failed_at}, expected {checkpoint}")
    for tool in expect.get("output_withheld", []):
        call = calls.get(tool)
        if call is None or call.output_action is None or call.output_action.value != "BLOCK":
            failures.append(f"{tool} output should have been withheld")
    for text in expect.get("answer_includes", []):
        if text.lower() not in answer_low:
            failures.append(f"answer missing {text!r}")
    for text in expect.get("answer_excludes", []):
        if text.lower() in answer_low:
            failures.append(f"answer leaked {text!r}")
    return failures


def run_agent_scenarios(scenarios: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    scenarios = scenarios if scenarios is not None else _load("agent_scenarios.yaml", "scenarios")
    results: list[ScenarioResult] = []
    for sc in scenarios:
        runtime = fresh_runtime()
        agent = sc["agent"]
        setup = sc.get("setup", {})
        if "trust" in setup:
            runtime.trust.override(
                SubjectType.AGENT,
                agent,
                setup["trust"],
                rationale="scenario setup",
                assessed_by="eval",
            )
        for prior in setup.get("prior", []):
            runtime.run_turn(agent=agent, session_id=sc["id"], message=prior)
        turn = runtime.run_turn(agent=agent, session_id=sc["id"], message=sc["message"])
        failures = _check(sc, turn)
        results.append(
            ScenarioResult(
                id=sc["id"],
                title=sc["title"],
                passed=not failures,
                failures=failures,
                blocked=turn.blocked,
                tools=[f"{c.tool}:{c.status.value}" for c in turn.tool_calls],
                duration_ms=turn.duration_ms,
            )
        )
    passed = sum(r.passed for r in results)
    return {
        "scenarios": len(results),
        "passed": passed,
        "pass_rate": _ratio(passed, len(results)),
        "results": [r.__dict__ for r in results],
    }


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
    for cat, v in fw["by_category"].items():
        lines.append(
            f"| {cat} | {v['n']} | {v['detected']} | {v['blocked']} | {v['detection_rate']:.0%} |"
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
    report = render_markdown(fw, ag)
    (args.out / "report.md").write_text(report, encoding="utf-8")

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

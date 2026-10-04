"""The red-team suites: a firewall benchmark and end-to-end agent scenarios.

Suites are YAML files in ``attack-scenarios/`` (``REDTEAM_SUITES_DIR``):

* ``firewall_cases.yaml`` — labelled malicious / benign texts, scanned on their
  channel. *Detected* = FLAG or BLOCK.
* ``agent_scenarios.yaml`` — full guarded agent turns, each in a fresh isolated
  runtime (own trust registry, knowledge base and gateway) with the deterministic
  rule-based brain, checked against expected outcomes.

Used by the dashboard's Red-team lab, the CLI ``evaluation/run_eval.py`` and the
CI security gate ``tests/test_evaluation.py``.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from app.agents.brain import RuleBasedBrain
from app.agents.runtime import AgentRuntime
from app.config import get_settings
from app.database.enums import SubjectType
from app.firewall.scanner import PromptFirewall
from app.firewall.schemas import ContentChannel, FirewallAction
from app.policies.config import get_global_config
from app.rag.embeddings import HashingEmbedder
from app.rag.knowledge_base import KnowledgeBase, seed_knowledge_base
from app.redteam.schemas import (
    AgentReport,
    CaseResult,
    CategoryStat,
    FirewallReport,
    ScenarioResult,
)
from app.tools.gateway import ToolGateway
from app.trust.engine import TrustEngine

Progress = Callable[[], None]
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def suites_dir() -> Path:
    configured = get_settings().redteam_suites_dir
    candidates = (
        [Path(configured)]
        if configured
        else [_BACKEND_ROOT.parent / "attack-scenarios", _BACKEND_ROOT / "attack-scenarios"]
    )
    for path in candidates:
        if (path / "firewall_cases.yaml").exists():
            return path
    raise FileNotFoundError(f"Red-team suites not found in: {', '.join(map(str, candidates))}")


def _load(name: str, key: str) -> list[dict[str, Any]]:
    return yaml.safe_load((suites_dir() / name).read_text(encoding="utf-8"))[key]


def load_firewall_cases() -> list[dict[str, Any]]:
    return _load("firewall_cases.yaml", "cases")


def load_agent_scenarios() -> list[dict[str, Any]]:
    return _load("agent_scenarios.yaml", "scenarios")


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
def run_firewall_benchmark(
    cases: list[dict[str, Any]] | None = None, progress: Progress | None = None
) -> FirewallReport:
    cases = cases if cases is not None else load_firewall_cases()
    fw = _firewall()
    tp = fp = tn = fn = blocked_malicious = blocked_benign = 0
    results: list[CaseResult] = []
    categories: dict[str, dict[str, int]] = {}

    for case in cases:
        start = time.perf_counter()
        verdict = fw.scan(case["text"], ContentChannel(case["channel"]))
        latency = (time.perf_counter() - start) * 1000
        detected = verdict.action != FirewallAction.ALLOW
        blocked = verdict.action == FirewallAction.BLOCK
        malicious = bool(case["malicious"])

        cat = categories.setdefault(case["category"], {"n": 0, "detected": 0, "blocked": 0})
        cat["n"] += 1
        cat["detected"] += detected
        cat["blocked"] += blocked
        if malicious:
            tp, fn = (tp + 1, fn) if detected else (tp, fn + 1)
            blocked_malicious += blocked and detected
        else:
            fp, tn = (fp + 1, tn) if detected else (fp, tn + 1)
            blocked_benign += blocked

        results.append(
            CaseResult(
                id=case["id"],
                category=case["category"],
                channel=case["channel"],
                malicious=malicious,
                action=verdict.action.value,
                score=verdict.score,
                rules=[m.rule_id for m in verdict.matches],
                detected=detected,
                correct=detected == malicious,
                latency_ms=round(latency, 3),
                text=case["text"],
            )
        )
        if progress:
            progress()

    latencies = [r.latency_ms for r in results] or [0.0]
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    return FirewallReport(
        cases=len(cases),
        malicious=tp + fn,
        benign=tn + fp,
        confusion={"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        precision=precision,
        recall=recall,
        f1=round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        false_positive_rate=_ratio(fp, fp + tn),
        block_rate_malicious=_ratio(blocked_malicious, tp + fn),
        block_rate_benign=_ratio(blocked_benign, tn + fp),
        latency_ms={
            "p50": round(statistics.median(latencies), 3),
            "p95": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 3),
            "max": round(max(latencies), 3),
        },
        by_category=[
            CategoryStat(category=k, detection_rate=_ratio(v["detected"], v["n"]), **v)
            for k, v in sorted(categories.items())
        ],
        results=results,
        misses=[r for r in results if r.malicious and not r.detected],
        false_positives=[r for r in results if not r.malicious and r.detected],
    )


# --------------------------------------------------------------------------- #
# Agent scenarios
# --------------------------------------------------------------------------- #
def fresh_runtime() -> AgentRuntime:
    """An isolated runtime: new trust registry, knowledge base and gateway."""
    settings = get_settings()
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


def check_scenario(scenario: dict[str, Any], turn: Any) -> list[str]:
    """Compare a turn with the scenario's expectations; returns the failures."""
    expect = scenario.get("expect", {})
    failures: list[str] = []
    calls = {c.tool: c for c in turn.tool_calls}
    answer_low = turn.answer.lower()

    def status(tool: str) -> str:
        call = calls.get(tool)
        return call.status.value if call else "no call"

    if "blocked" in expect and turn.blocked != expect["blocked"]:
        failures.append(f"blocked={turn.blocked}, expected {expect['blocked']}")
    for tool in expect.get("executed", []):
        if status(tool) != "EXECUTED":
            failures.append(f"{tool} should have executed (got {status(tool)})")
    for tool in expect.get("pending", []):
        if status(tool) != "PENDING":
            failures.append(f"{tool} should be waiting for approval (got {status(tool)})")
    for tool, checkpoint in expect.get("denied", {}).items():
        call = calls.get(tool)
        if call is None or call.status.value != "DENIED":
            failures.append(f"{tool} should have been denied (got {status(tool)})")
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


def run_agent_scenarios(
    scenarios: list[dict[str, Any]] | None = None, progress: Progress | None = None
) -> AgentReport:
    scenarios = scenarios if scenarios is not None else load_agent_scenarios()
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
        failures = check_scenario(sc, turn)
        results.append(
            ScenarioResult(
                id=sc["id"],
                title=sc["title"],
                agent=agent,
                message=sc["message"],
                passed=not failures,
                failures=failures,
                blocked=turn.blocked,
                tools=[f"{c.tool}:{c.status.value}" for c in turn.tool_calls],
                duration_ms=turn.duration_ms,
            )
        )
        if progress:
            progress()
    passed = sum(r.passed for r in results)
    return AgentReport(
        scenarios=len(results),
        passed=passed,
        pass_rate=_ratio(passed, len(results)),
        results=results,
    )

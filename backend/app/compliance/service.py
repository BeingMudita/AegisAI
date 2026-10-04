"""Builds the threat-coverage report, checking evidence against the latest red-team run."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from app.compliance.catalog import CONTROLS, FRAMEWORKS
from app.compliance.schemas import (
    CoverageReport,
    Evidence,
    Framework,
    ThreatCoverage,
    ThreatDef,
)
from app.redteam.schemas import RedTeamRun, RunSummary
from app.redteam.service import get_redteam_service

# A firewall category counts as passing evidence at this detection rate.
CATEGORY_PASS = 0.9


def _evidence(ref: str, run: RedTeamRun | None) -> Evidence:
    kind, _, key = ref.partition(":")
    if kind == "test":
        return Evidence(kind="test", ref=key, label=key.rsplit("/", 1)[-1], status="static",
                        detail="Unit test in the CI suite")  # fmt: skip

    if kind == "category":
        label = key.replace("_", " ").capitalize()
        stats = (
            run
            and run.firewall
            and next((c for c in run.firewall.by_category if c.category == key), None)
        )
        if not stats:
            return Evidence(kind="category", ref=key, label=label, status="not_run")
        rate = stats.detection_rate
        return Evidence(
            kind="category",
            ref=key,
            label=label,
            status="pass" if rate >= CATEGORY_PASS else "weak" if rate > 0 else "fail",
            detail=f"{stats.detected}/{stats.n} detected ({rate:.0%})",
        )

    scenario = run and run.agents and next((s for s in run.agents.results if s.id == key), None)
    if not scenario:
        return Evidence(kind="scenario", ref=key, label=key, status="not_run")
    return Evidence(
        kind="scenario",
        ref=key,
        label=f"{key} {scenario.title}",
        status="pass" if scenario.passed else "fail",
        detail="; ".join(scenario.failures) or None,
    )


def _coverage(threat: ThreatDef, run: RedTeamRun | None) -> ThreatCoverage:
    evidence = [_evidence(ref, run) for ref in threat.evidence]
    live = [e for e in evidence if e.status != "static"]
    verified = (
        None
        if not live or any(e.status == "not_run" for e in live)
        else all(e.status == "pass" for e in live)
    )
    return ThreatCoverage(
        **threat.model_dump(exclude={"evidence"}), evidence=evidence, verified=verified
    )


def coverage_report() -> CoverageReport:
    run = get_redteam_service().latest_completed()
    frameworks = []
    for fw in FRAMEWORKS:
        items = [_coverage(t, run) for t in fw["items"]]
        frameworks.append(
            Framework(
                id=fw["id"],
                name=fw["name"],
                version=fw["version"],
                url=fw["url"],
                items=items,
                summary=dict(Counter(i.status for i in items)),
            )
        )
    return CoverageReport(
        generated_at=datetime.now(timezone.utc),
        frameworks=frameworks,
        controls=CONTROLS,
        evidence_run=RunSummary.of(run) if run else None,
    )

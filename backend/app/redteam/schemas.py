"""Pydantic schemas for red-team runs."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

Suite = Literal["firewall", "agents"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CaseResult(BaseModel):
    """One labelled input scanned by the firewall."""

    id: str
    category: str
    channel: str
    malicious: bool
    action: str
    score: float
    rules: list[str]
    detected: bool
    correct: bool  # detected malicious input, or allowed benign input
    latency_ms: float
    text: str


class CategoryStat(BaseModel):
    category: str
    n: int
    detected: int
    blocked: int
    detection_rate: float


class FirewallReport(BaseModel):
    cases: int
    malicious: int
    benign: int
    confusion: dict[str, int]
    precision: float
    recall: float
    f1: float
    false_positive_rate: float
    block_rate_malicious: float
    block_rate_benign: float
    latency_ms: dict[str, float]
    by_category: list[CategoryStat]
    results: list[CaseResult]
    misses: list[CaseResult]
    false_positives: list[CaseResult]


class ScenarioResult(BaseModel):
    """One end-to-end agent scenario."""

    id: str
    title: str
    agent: str
    message: str
    passed: bool
    failures: list[str] = Field(default_factory=list)
    blocked: bool = False
    tools: list[str] = Field(default_factory=list)
    duration_ms: float = 0.0


class AgentReport(BaseModel):
    scenarios: int
    passed: int
    pass_rate: float
    results: list[ScenarioResult]


class RedTeamRun(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: Literal["running", "completed", "failed"] = "running"
    suites: list[Suite]
    started_by: str
    started_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None
    progress_done: int = 0
    progress_total: int = 0
    firewall: FirewallReport | None = None
    agents: AgentReport | None = None
    error: str | None = None


class RunRequest(BaseModel):
    suites: list[Suite] = Field(default_factory=lambda: ["firewall", "agents"], min_length=1)


class RunSummary(BaseModel):
    """A run without its case-level detail, for history lists."""

    id: str
    status: str
    suites: list[str]
    started_by: str
    started_at: datetime
    finished_at: datetime | None
    recall: float | None = None
    precision: float | None = None
    false_positive_rate: float | None = None
    scenarios_passed: int | None = None
    scenarios_total: int | None = None

    @classmethod
    def of(cls, run: RedTeamRun) -> RunSummary:
        return cls(
            id=run.id,
            status=run.status,
            suites=list(run.suites),
            started_by=run.started_by,
            started_at=run.started_at,
            finished_at=run.finished_at,
            recall=run.firewall.recall if run.firewall else None,
            precision=run.firewall.precision if run.firewall else None,
            false_positive_rate=run.firewall.false_positive_rate if run.firewall else None,
            scenarios_passed=run.agents.passed if run.agents else None,
            scenarios_total=run.agents.scenarios if run.agents else None,
        )

"""Schemas for the threat-coverage report."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.redteam.schemas import RunSummary

CoverageStatus = Literal["mitigated", "partial", "gap"]
EvidenceStatus = Literal["pass", "weak", "fail", "not_run", "static"]


class Control(BaseModel):
    id: str
    name: str
    description: str
    page: str | None = None  # dashboard route that shows the control in action
    code: list[str] = Field(default_factory=list)


class ThreatDef(BaseModel):
    """A threat as written in the catalog (evidence as references)."""

    id: str
    name: str
    description: str
    status: CoverageStatus
    controls: list[str]
    evidence: list[str]
    residual: str


class Evidence(BaseModel):
    kind: Literal["category", "scenario", "test"]
    ref: str
    label: str
    status: EvidenceStatus
    detail: str | None = None


class ThreatCoverage(BaseModel):
    id: str
    name: str
    description: str
    status: CoverageStatus
    controls: list[str]
    evidence: list[Evidence]
    residual: str
    verified: bool | None  # all live evidence passed in the latest run (None = no run yet)


class Framework(BaseModel):
    id: str
    name: str
    version: str
    url: str
    items: list[ThreatCoverage]
    summary: dict[str, int]


class CoverageReport(BaseModel):
    generated_at: datetime
    frameworks: list[Framework]
    controls: list[Control]
    evidence_run: RunSummary | None

"""Pydantic schemas for tool requests and the gateway's decisions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.database.enums import ToolRequestStatus, ToolRiskLevel
from app.firewall.schemas import FirewallAction


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ToolCallRequest(BaseModel):
    agent: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class CheckResult(BaseModel):
    """The outcome of one gateway checkpoint."""

    checkpoint: str  # registry | policy | domain | firewall | trust | rate_limit | output | dlp
    passed: bool
    detail: str


class ToolCallResult(BaseModel):
    """A tool request and everything the gateway decided about it
    (mirrors the ``tool_requests`` table)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent: str
    session_id: str | None = None
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: ToolRequestStatus = ToolRequestStatus.PENDING
    decision_reason: str = ""
    checks: list[CheckResult] = Field(default_factory=list)
    output: str | None = None
    output_action: FirewallAction | None = None
    redactions: dict[str, int] = Field(default_factory=dict)
    requested_at: datetime = Field(default_factory=_now)
    decided_at: datetime | None = None
    # Human approval (high-risk tools)
    expires_at: datetime | None = None
    reviewed_by: str | None = None
    review_note: str | None = None
    reviewed_at: datetime | None = None

    @property
    def executed(self) -> bool:
        return self.status == ToolRequestStatus.EXECUTED

    @property
    def pending(self) -> bool:
        return self.status == ToolRequestStatus.PENDING


class ToolInfo(BaseModel):
    name: str
    description: str
    risk_level: ToolRiskLevel
    enabled: bool
    required_trust: float
    rate_limit_per_min: int | None
    data_category: str | None
    parameters: dict[str, str]
    domain_checked_argument: str | None
    requires_approval: bool = False


class ReviewRequest(BaseModel):
    note: str = Field(default="", max_length=500)


class ApprovalQueue(BaseModel):
    pending: list[ToolCallResult]
    recent: list[ToolCallResult]
    ttl_minutes: int

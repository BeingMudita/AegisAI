"""Pydantic schemas for audit telemetry."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.database.enums import SecurityEventType, SecuritySeverity


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SecurityEventRecord(BaseModel):
    """One security-relevant decision or incident (mirrors ``security_events``)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: SecurityEventType
    severity: SecuritySeverity = SecuritySeverity.INFO
    agent: str | None = None
    session_id: str | None = None
    source: str  # the component that raised it: firewall, policy, trust, tools, agent
    description: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class DecisionCount(BaseModel):
    """How many allow / deny decisions a component has made."""

    component: str
    allowed: int = 0
    denied: int = 0


class TelemetrySummary(BaseModel):
    """Aggregates for the dashboard."""

    total_events: int
    by_type: dict[str, int]
    by_severity: dict[str, int]
    by_agent: dict[str, int]
    decisions: list[DecisionCount]

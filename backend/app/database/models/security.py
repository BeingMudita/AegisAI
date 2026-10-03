"""Security tables: trust scores and assessments, decision counters, tool definitions and
requests, security events.

Audit-style tables (security_events, tool_requests, trust_assessments) key agents and
sessions by name / id string rather than foreign key: audit records must outlive the
rows they describe, and some events (API scans, ingestion) have no session at all.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, uuid_pk
from app.database.enums import (
    SecurityEventType,
    SecuritySeverity,
    SubjectType,
    ToolRequestStatus,
    ToolRiskLevel,
    TrustLevel,
)


class TrustScoreRow(Base):
    """The current trust score of one subject (one row per subject)."""

    __tablename__ = "trust_scores"
    __table_args__ = (PrimaryKeyConstraint("subject_type", "subject_key"),)

    subject_type: Mapped[SubjectType] = mapped_column(Enum(SubjectType, name="trust_subject_type"))
    subject_key: Mapped[str] = mapped_column(String(255))  # lower-cased id, the lookup key
    subject_id: Mapped[str] = mapped_column(String(255))  # display form
    score: Mapped[float] = mapped_column(Float)
    assessments: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TrustAssessment(Base):
    """A point-in-time trust change for an agent, source, or tool."""

    __tablename__ = "trust_assessments"

    id: Mapped[uuid.UUID] = uuid_pk()
    subject_type: Mapped[SubjectType] = mapped_column(
        Enum(SubjectType, name="trust_subject_type"), index=True
    )
    subject_key: Mapped[str] = mapped_column(String(255), index=True)
    subject_id: Mapped[str] = mapped_column(String(255))
    score: Mapped[float] = mapped_column(Float, default=0.0)
    previous: Mapped[float] = mapped_column(Float, default=0.0)
    level: Mapped[TrustLevel] = mapped_column(
        Enum(TrustLevel, name="trust_level"), default=TrustLevel.UNTRUSTED
    )
    signal: Mapped[str] = mapped_column(String(64))
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class DecisionCounter(Base):
    """Allowed / denied decision totals per checkpoint component."""

    __tablename__ = "decision_counters"

    component: Mapped[str] = mapped_column(String(64), primary_key=True)
    allowed: Mapped[int] = mapped_column(BigInteger, default=0)
    denied: Mapped[int] = mapped_column(BigInteger, default=0)


class ToolDefinition(Base, TimestampMixin):
    """The registry of tools an agent may request to use (seeded from the policy file)."""

    __tablename__ = "tool_definitions"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    risk_level: Mapped[ToolRiskLevel] = mapped_column(
        Enum(ToolRiskLevel, name="tool_risk_level"), default=ToolRiskLevel.MEDIUM
    )
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class ToolRequest(Base):
    """An agent's request to invoke a tool, and everything the gateway decided."""

    __tablename__ = "tool_requests"

    id: Mapped[uuid.UUID] = uuid_pk()
    agent: Mapped[str] = mapped_column(String(128), index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tool: Mapped[str] = mapped_column(String(128), index=True)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[ToolRequestStatus] = mapped_column(
        Enum(ToolRequestStatus, name="tool_request_status"),
        default=ToolRequestStatus.PENDING,
        index=True,
    )
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_action: Mapped[str | None] = mapped_column(String(16), nullable=True)
    redactions: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SecurityEvent(Base):
    """An audit record of a security-relevant decision or incident."""

    __tablename__ = "security_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    event_type: Mapped[SecurityEventType] = mapped_column(
        Enum(SecurityEventType, name="security_event_type"), index=True
    )
    severity: Mapped[SecuritySeverity] = mapped_column(
        Enum(SecuritySeverity, name="security_severity"),
        default=SecuritySeverity.INFO,
        index=True,
    )
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class RateLimitHit(Base):
    """One counted attempt for a shared rolling-window limiter (tool calls, logins)."""

    __tablename__ = "rate_limit_hits"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(255), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

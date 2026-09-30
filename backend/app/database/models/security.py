"""Security tables: trust_assessments, tool_definitions, tool_requests, security_events."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, uuid_pk
from app.database.enums import (
    SecurityEventType,
    SecuritySeverity,
    SubjectType,
    ToolRequestStatus,
    ToolRiskLevel,
    TrustLevel,
)


class TrustAssessment(Base):
    """A point-in-time trust score for an agent, source, or tool."""

    __tablename__ = "trust_assessments"

    id: Mapped[uuid.UUID] = uuid_pk()
    subject_type: Mapped[SubjectType] = mapped_column(
        Enum(SubjectType, name="trust_subject_type"), index=True
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    level: Mapped[TrustLevel] = mapped_column(
        Enum(TrustLevel, name="trust_level"), default=TrustLevel.UNTRUSTED
    )
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class ToolDefinition(Base, TimestampMixin):
    """The registry of tools an agent may request to use."""

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

    requests: Mapped[list["ToolRequest"]] = relationship(back_populates="tool")


class ToolRequest(Base):
    """An agent's request to invoke a tool, and the decision made about it."""

    __tablename__ = "tool_requests"

    id: Mapped[uuid.UUID] = uuid_pk()
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tool_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tool_definitions.id", ondelete="CASCADE"), index=True
    )
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[ToolRequestStatus] = mapped_column(
        Enum(ToolRequestStatus, name="tool_request_status"),
        default=ToolRequestStatus.PENDING,
        index=True,
    )
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tool: Mapped["ToolDefinition"] = relationship(back_populates="requests")


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
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

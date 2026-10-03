"""Core identity & governance tables: users, agents, policies, agent sessions, their runs
and turns."""

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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.auth.roles import Role
from app.database.base import Base, TimestampMixin, uuid_pk
from app.database.enums import AgentStatus, SessionStatus


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role, name="user_role"), default=Role.AGENT)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)

    agents: Mapped[list["Agent"]] = relationship(back_populates="owner")


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, name="agent_status"), default=AgentStatus.ACTIVE
    )
    trust_score: Mapped[float] = mapped_column(Float, default=0.5)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    owner: Mapped["User | None"] = relationship(back_populates="agents")
    policies: Mapped[list["Policy"]] = relationship(back_populates="agent")
    sessions: Mapped[list["AgentSession"]] = relationship(back_populates="agent")


class Policy(Base, TimestampMixin):
    """A declarative policy governing what an agent may do.

    Mirrors the agent-policy JSON: allowed/blocked tools, allowed domains,
    and sensitive-data categories. ``raw`` keeps the original document.
    """

    __tablename__ = "policies"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(128), index=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )
    allowed_tools: Mapped[list[str]] = mapped_column(JSONB, default=list)
    blocked_tools: Mapped[list[str]] = mapped_column(JSONB, default=list)
    allowed_domains: Mapped[list[str]] = mapped_column(JSONB, default=list)
    sensitive_data: Mapped[list[str]] = mapped_column(JSONB, default=list)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    agent: Mapped["Agent | None"] = relationship(back_populates="policies")


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, name="session_status"), default=SessionStatus.ACTIVE
    )
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    agent: Mapped["Agent"] = relationship(back_populates="sessions")
    user: Mapped["User | None"] = relationship()


class SessionRun(Base):
    """One attempt to run a turn in a session.

    It is the session's execution lock (a row in ``running`` state whose lease has
    not expired), the progress record every API worker can read, and the replay
    guard: the unique (session_id, request_id) pair rejects a repeated request ID
    on any worker, even after a failed attempt.
    """

    __tablename__ = "session_runs"
    __table_args__ = (UniqueConstraint("session_id", "request_id", name="uq_session_runs_request"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"), index=True
    )
    request_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    current_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AgentTurnRow(Base):
    """A completed agent turn (the full guarded result, kept as JSON evidence)."""

    __tablename__ = "agent_turns"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"), index=True
    )
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

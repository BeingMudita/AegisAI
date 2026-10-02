"""Pydantic schemas for agents, sessions and turns."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.database.enums import SessionStatus
from app.rag.schemas import DroppedChunk, RetrievedChunk
from app.tools.schemas import ToolCallResult, ToolInfo


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AgentAction(BaseModel):
    """What the brain wants to do next."""

    kind: Literal["tool", "answer"]
    tool: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    thought: str = ""


@dataclass
class TurnContext:
    """Everything the brain may look at when deciding or answering."""

    agent: str
    message: str
    tools: list[ToolInfo]
    context: list[RetrievedChunk] = field(default_factory=list)
    steps: list[ToolCallResult] = field(default_factory=list)
    history: list[tuple[str, str]] = field(default_factory=list)


class TraceEntry(BaseModel):
    """One step of the security pipeline, shown in the dashboard."""

    stage: str  # input_firewall | retrieval | plan | tool | respond | output_guard
    status: str  # passed | flagged | blocked | denied | executed | skipped | redacted | failed
    detail: str
    data: dict[str, Any] = Field(default_factory=dict)


class AgentTurn(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    agent: str
    message: str
    answer: str
    blocked: bool = False
    brain: str
    trace: list[TraceEntry] = Field(default_factory=list)
    tool_calls: list[ToolCallResult] = Field(default_factory=list)
    context: list[RetrievedChunk] = Field(default_factory=list)
    dropped: list[DroppedChunk] = Field(default_factory=list)
    redactions: dict[str, int] = Field(default_factory=dict)
    duration_ms: float = 0.0
    created_at: datetime = Field(default_factory=_now)


class AgentSessionRecord(BaseModel):
    """A conversation between a principal and an agent (mirrors ``agent_sessions``)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent: str
    owner: str
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: datetime = Field(default_factory=_now)
    ended_at: datetime | None = None
    turns: list[AgentTurn] = Field(default_factory=list)


class SessionSummary(BaseModel):
    id: str
    agent: str
    owner: str
    status: SessionStatus
    created_at: datetime
    ended_at: datetime | None
    turns: int
    blocked_turns: int


class CreateSessionRequest(BaseModel):
    agent: str


class MessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class AgentInfo(BaseModel):
    name: str
    trust_score: float
    trust_level: str
    allowed_tools: list[str]
    blocked_tools: list[str]
    allowed_domains: list[str]
    sensitive_data: list[str]

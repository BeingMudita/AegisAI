"""Schemas for multi-agent delegation requests and results."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.tools.schemas import ToolCallResult


class DelegationRequest(BaseModel):
    caller: str = Field(description="The agent delegating the action.")
    callee: str = Field(description="The agent asked to perform it.")
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None


class DelegationResult(BaseModel):
    """The outcome of a delegation: the orchestration decision plus the tool result."""

    tenant: str
    caller: str
    callee: str
    tool: str
    allowed: bool  # was the delegation itself permitted (regardless of the tool outcome)
    reason: str
    checkpoint: str | None = None  # which delegation guard failed, if any
    tool_result: ToolCallResult | None = None  # the gateway's result when the delegation proceeded

"""Framework-neutral request/response shapes for the proxy's own endpoints,
plus the small transforms that fold an :class:`AegisDecision` back into them.

The OpenAI-compatible endpoint (``/v1/chat/completions``) uses the OpenAI
*adapter* instead; these schemas are for the proxy-native ``/v1/proxy/*`` API,
which is deliberately minimal and independent of any vendor format.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.platform.protocol.events import ToolCall
from app.platform.protocol.schemas import AegisDecision, Decision


class ProxyMessage(BaseModel):
    role: str = "user"
    content: str = ""


class ProxyChatRequest(BaseModel):
    agent: str
    session_id: str | None = None
    messages: list[ProxyMessage] = Field(default_factory=list)
    model: str | None = None

    @property
    def last_user_message(self) -> str:
        for message in reversed(self.messages):
            if message.role == "user":
                return message.content
        return ""

    @property
    def history(self) -> list[tuple[str, str]]:
        """(user, assistant) pairs preceding the final user message."""
        pairs: list[tuple[str, str]] = []
        pending: str | None = None
        for message in self.messages:
            if message.role == "user":
                pending = message.content
            elif message.role == "assistant" and pending is not None:
                pairs.append((pending, message.content))
                pending = None
        # Drop the final, still-unanswered user message from the history.
        return pairs


class ProxyToolRequest(BaseModel):
    agent: str
    session_id: str | None = None
    tool: ToolCall
    context: dict[str, Any] = Field(default_factory=dict)


class ProxyOutputRequest(BaseModel):
    agent: str
    session_id: str | None = None
    text: str


class ProxyChatResponse(BaseModel):
    """The result of a guarded chat turn through the proxy."""

    agent: str
    session_id: str
    decision: Decision
    reason: str
    message: str  # the (possibly sanitized / refused) assistant reply
    input_decisions: list[AegisDecision] = Field(default_factory=list)
    output_decision: AegisDecision | None = None
    redactions: dict[str, int] = Field(default_factory=dict)


def first_block(decisions: list[AegisDecision]) -> AegisDecision | None:
    """The first blocking decision in a list, if any."""
    return next((d for d in decisions if d.decision == Decision.BLOCK), None)

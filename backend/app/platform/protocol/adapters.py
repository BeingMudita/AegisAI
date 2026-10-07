"""The adapter contract.

An adapter is the *only* framework-specific code in AegisAI. It translates a
particular agent framework's wire format (OpenAI chat completions, an MCP tool
call, …) into :class:`AegisEvent`s on the way in, and turns an
:class:`AegisDecision` back into that framework's response shape on the way out.

    framework request  ──normalize_*──▶  AegisEvent
    AegisDecision      ──build_response─▶  framework response

Everything *between* those two steps is the framework-neutral
:class:`~app.platform.protocol.engine.SecurityEngine`. Concrete adapters live in
:mod:`app.platform.adapters`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.platform.protocol.events import AegisEvent
from app.platform.protocol.schemas import AegisDecision


class AgentAdapter(ABC):
    """Translate one framework to and from the Aegis event protocol."""

    #: Short identifier used by the adapter registry (e.g. ``"openai"``).
    name: str = "adapter"

    @abstractmethod
    def normalize_input(self, request: Any, *, agent: str, session_id: str) -> list[AegisEvent]:
        """The untrusted user message(s) in ``request`` as INPUT events."""

    @abstractmethod
    def normalize_tool_call(
        self, response: Any, *, agent: str, session_id: str
    ) -> list[AegisEvent]:
        """Any tool call(s) the model proposed as TOOL_PROPOSAL events."""

    @abstractmethod
    def normalize_output(self, response: Any, *, agent: str, session_id: str) -> AegisEvent:
        """The assistant's outbound text in ``response`` as an OUTPUT event."""

    @abstractmethod
    def build_response(self, response: Any, decisions: list[AegisDecision]) -> Any:
        """Fold the engine's decisions back into a framework-shaped response."""

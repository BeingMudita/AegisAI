"""The OpenAI-compatible adapter.

The OpenAI Chat Completions schema is the lingua franca of the LLM ecosystem —
OpenAI, vLLM, Ollama, LM Studio, Together, Groq and many others all speak it. So
one adapter here lets AegisAI sit transparently in front of a very large slice of
existing agents: point the agent's ``base_url`` at the proxy and nothing else
changes.

This adapter only *translates*; it never decides. It turns the request/response
dicts into :class:`AegisEvent`s and folds :class:`AegisDecision`s back into an
OpenAI-shaped response.
"""

from __future__ import annotations

import json
from typing import Any

from app.platform.protocol.adapters import AgentAdapter
from app.platform.protocol.events import AegisEvent
from app.platform.protocol.schemas import AegisDecision, Decision


def _assistant_message(response: dict) -> dict:
    """The first choice's assistant message (or an empty one)."""
    choices = response.get("choices") or []
    if not choices:
        return {}
    return choices[0].get("message") or {}


class OpenAIAdapter(AgentAdapter):
    """Translate OpenAI Chat Completions to and from the Aegis event protocol."""

    name = "openai"

    # ------------------------------------------------------------- inbound
    def normalize_input(self, request: dict, *, agent: str, session_id: str) -> list[AegisEvent]:
        """Every ``user`` message is untrusted input to be screened.

        Only the roles an end user controls (``user``) are treated as input;
        ``system`` and ``assistant`` messages are the application's own.
        """
        events: list[AegisEvent] = []
        for message in request.get("messages", []):
            if message.get("role") != "user":
                continue
            events.append(
                AegisEvent.input(
                    agent,
                    _content_text(message.get("content")),
                    session_id=session_id,
                    model=request.get("model"),
                )
            )
        return events

    def normalize_tool_call(
        self, response: dict, *, agent: str, session_id: str
    ) -> list[AegisEvent]:
        """Each ``tool_calls`` entry the model proposed becomes a TOOL_PROPOSAL."""
        events: list[AegisEvent] = []
        for call in _assistant_message(response).get("tool_calls") or []:
            fn = call.get("function") or {}
            events.append(
                AegisEvent.tool_proposal(
                    agent,
                    fn.get("name", ""),
                    _parse_arguments(fn.get("arguments")),
                    session_id=session_id,
                )
            )
        return events

    def normalize_output(self, response: dict, *, agent: str, session_id: str) -> AegisEvent:
        """The assistant's text content becomes the OUTPUT event."""
        return AegisEvent.output(
            agent, _content_text(_assistant_message(response).get("content")), session_id=session_id
        )

    # ------------------------------------------------------------ outbound
    def build_response(self, response: dict, decisions: list[AegisDecision]) -> dict:
        """Apply the decisions to a copy of the OpenAI response.

        * A blocked tool call is stripped from ``tool_calls`` (the model never
          gets to run it); when that empties the list it is removed entirely.
        * Sanitized / redacted OUTPUT text replaces the assistant content.
        """
        out = json.loads(json.dumps(response))  # deep copy
        message = _assistant_message(out)
        tool_calls = message.get("tool_calls") or []
        tool_decisions = [d for d in decisions if d.event_type.value == "TOOL_PROPOSAL"]

        if tool_calls and tool_decisions:
            kept = []
            blocked_reasons = []
            for call, decision in zip(tool_calls, tool_decisions, strict=False):
                if decision.decision == Decision.BLOCK:
                    fn = (call.get("function") or {}).get("name", "tool")
                    blocked_reasons.append(f"{fn}: {decision.reason}")
                else:
                    kept.append(call)
            if kept:
                message["tool_calls"] = kept
            else:
                message.pop("tool_calls", None)
            if blocked_reasons and not message.get("content"):
                message["content"] = (
                    "[AegisAI blocked a tool call] " + "; ".join(blocked_reasons)
                )

        output_decision = next(
            (d for d in decisions if d.event_type.value == "OUTPUT"), None
        )
        if output_decision is not None and output_decision.sanitized_text is not None:
            message["content"] = output_decision.sanitized_text
        return out

    # ------------------------------------------------------------ helpers
    @staticmethod
    def refusal_response(model: str, reason: str) -> dict:
        """A minimal, valid OpenAI completion carrying a refusal — returned when
        the input itself is blocked and must never reach the upstream model."""
        return {
            "id": "aegis-blocked",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": reason},
                    "finish_reason": "content_filter",
                }
            ],
            "aegis": {"decision": "BLOCK", "reason": reason},
        }


def _content_text(content: Any) -> str:
    """Flatten OpenAI message content (a string, or a list of content parts)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # multimodal content parts
        return " ".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        ).strip()
    return str(content)


def _parse_arguments(raw: Any) -> dict:
    """Tool-call arguments arrive as a JSON string; be forgiving if they don't."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"_": parsed}
        except json.JSONDecodeError:
            return {"_raw": raw}
    return {}

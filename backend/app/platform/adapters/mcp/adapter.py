"""MCP ↔ Aegis event protocol translation (JSON-RPC 2.0 ``tools/call``)."""

from __future__ import annotations

from typing import Any

from app.platform.protocol.adapters import AgentAdapter
from app.platform.protocol.events import AegisEvent
from app.platform.protocol.schemas import AegisDecision, Decision


def _result_text(result: dict) -> str:
    """Flatten an MCP tool result's ``content`` blocks into plain text."""
    content = result.get("content")
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        ).strip()
    if isinstance(content, str):
        return content
    return ""


class McpAdapter(AgentAdapter):
    """Translate MCP ``tools/call`` requests and results to Aegis events."""

    name = "mcp"

    def normalize_input(self, request: dict, *, agent: str, session_id: str) -> list[AegisEvent]:
        """MCP carries tool traffic, not user prompts — nothing to screen here."""
        return []

    def normalize_tool_call(
        self, request: dict, *, agent: str, session_id: str
    ) -> list[AegisEvent]:
        """A ``tools/call`` request becomes one TOOL_PROPOSAL."""
        if request.get("method") != "tools/call":
            return []
        params = request.get("params") or {}
        return [
            AegisEvent.tool_proposal(
                agent,
                params.get("name", ""),
                params.get("arguments") or {},
                session_id=session_id,
            )
        ]

    def normalize_output(self, response: dict, *, agent: str, session_id: str) -> AegisEvent:
        """A ``tools/call`` result becomes a TOOL_RESULT to screen on the way back."""
        result = response.get("result") or {}
        return AegisEvent.tool_result(
            agent, response.get("_tool", "tool"), _result_text(result), session_id=session_id
        )

    def build_response(self, response: dict, decisions: list[AegisDecision]) -> dict:
        """Turn a blocking decision into a JSON-RPC-shaped MCP error result."""
        blocking = next((d for d in decisions if d.decision == Decision.BLOCK), None)
        if blocking is not None:
            return {
                "jsonrpc": "2.0",
                "id": response.get("id"),
                "result": {
                    "isError": True,
                    "content": [
                        {"type": "text", "text": f"[AegisAI blocked] {blocking.reason}"}
                    ],
                },
                "aegis": {"decision": "BLOCK", "reason_code": blocking.reason_code},
            }
        out = dict(response)
        sanitized = next(
            (d.sanitized_text for d in decisions if d.sanitized_text is not None), None
        )
        if sanitized is not None and isinstance(out.get("result"), dict):
            out["result"] = dict(out["result"])
            out["result"]["content"] = [{"type": "text", "text": sanitized}]
        return out

    def error(self, request_id: Any, message: str) -> dict:
        """A JSON-RPC error object (used when the gateway refuses outright)."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": message},
        }

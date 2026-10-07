"""Concrete adapters and their registry.

:class:`~app.platform.protocol.adapters.AgentAdapter` (the abstract contract)
lives beside the protocol; the concrete implementations live here. A small
registry lets the proxy pick an adapter by name — the value of an
``upstream.type`` in ``aegis-agent.yaml`` or an ``--upstream-type`` flag.
"""

from __future__ import annotations

from app.platform.protocol.adapters import AgentAdapter

_REGISTRY: dict[str, AgentAdapter] = {}


def register_adapter(adapter: AgentAdapter) -> AgentAdapter:
    """Register an adapter instance under its ``name``."""
    _REGISTRY[adapter.name] = adapter
    return adapter


def get_adapter(name: str) -> AgentAdapter:
    """Return the registered adapter called ``name`` (``KeyError`` if unknown)."""
    try:
        return _REGISTRY[name]
    except KeyError as exc:  # noqa: TRY003
        known = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise KeyError(f"No adapter '{name}'. Registered adapters: {known}.") from exc


def available_adapters() -> list[str]:
    return sorted(_REGISTRY)


# Register the built-ins on import.
from app.platform.adapters.mcp import McpAdapter  # noqa: E402
from app.platform.adapters.openai import OpenAIAdapter  # noqa: E402

register_adapter(OpenAIAdapter())
register_adapter(McpAdapter())

__all__ = [
    "AgentAdapter",
    "available_adapters",
    "get_adapter",
    "register_adapter",
]

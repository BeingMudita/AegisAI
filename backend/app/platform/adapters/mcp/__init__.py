"""The Model Context Protocol (MCP) adapter.

MCP is how agents reach external tools — files, databases, email, SaaS APIs —
each behind an MCP server::

                 AI Agent
                    │
                    ▼
              Aegis MCP Proxy
                    │
          ┌─────────┼─────────┐
          ▼         ▼         ▼
       Files       DB       Email
        MCP        MCP        MCP

Every ``tools/call`` is normalized to an Aegis ``TOOL_PROPOSAL`` and run through
the deny-by-default tool gateway before it is forwarded to its MCP server; every
``tools/call`` *result* is normalized to a ``TOOL_RESULT`` and screened on the
way back. The gateway's dry-run ``authorize`` — built as the enforcement hook for
exactly this — is what decides.
"""

from __future__ import annotations

from app.platform.adapters.mcp.adapter import McpAdapter

__all__ = ["McpAdapter"]

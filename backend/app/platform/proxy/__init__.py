"""The generic Aegis proxy — the universal runtime integration layer.

Route an existing agent's LLM and tool traffic through AegisAI without
rewriting its security logic: point it at the proxy and get input screening,
trust-gated tool authorization, and output DLP for free.

    from app.platform.proxy import create_proxy_app, router
"""

from __future__ import annotations

from app.platform.proxy.router import router
from app.platform.proxy.server import Upstream, create_proxy_app, run

__all__ = ["Upstream", "create_proxy_app", "router", "run"]

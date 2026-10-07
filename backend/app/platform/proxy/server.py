"""The standalone Aegis proxy server.

``aegis proxy`` starts this: a small FastAPI app that mounts the proxy router
and nothing else, so it can run on its own port in front of an existing agent::

    Agent ──▶ http://localhost:9000 (Aegis proxy) ──▶ real LLM / tools

The same :data:`router` is also mounted into the main AegisAI app, so the proxy
endpoints are available there too (``/v1/proxy/*`` and ``/v1/chat/completions``).

The *upstream* is where screened traffic goes next. Point it at any
OpenAI-compatible endpoint (OpenAI, vLLM, Ollama, LM Studio, …); leave it unset
and the proxy uses the built-in AegisAI runtime as the upstream, so a demo needs
no external model at all.
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from app import __version__
from app.platform.adapters import get_adapter
from app.platform.proxy.config import AegisAgentConfig

DEFAULT_AGENT = "proxy-agent"


class Upstream:
    """Where screened requests are forwarded after inspection."""

    def __init__(self, url: str | None = None, *, timeout: float = 60.0) -> None:
        self.url = url.rstrip("/") if url else None
        self.timeout = timeout

    @property
    def is_local(self) -> bool:
        """True when there is no external model — the runtime answers instead."""
        return self.url is None

    def chat_completion(self, body: dict, *, agent: str) -> dict:
        """Forward an OpenAI-shaped chat request and return an OpenAI-shaped reply."""
        if self.url:
            endpoint = (
                self.url
                if self.url.endswith("/chat/completions")
                else f"{self.url}/v1/chat/completions"
            )
            response = httpx.post(endpoint, json=body, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        return self._runtime_completion(body, agent=agent)

    def _runtime_completion(self, body: dict, *, agent: str) -> dict:
        """Answer with the built-in AegisAI runtime (no external model)."""
        from app.agents.runtime import get_runtime

        messages = body.get("messages", [])
        user = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), ""
        )
        turn = get_runtime().run_turn(
            agent=agent, session_id=body.get("_session", "proxy"), message=user, history=[]
        )
        return {
            "id": f"aegis-{turn.session_id}",
            "object": "chat.completion",
            "model": body.get("model", "aegis-runtime"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": turn.answer},
                    "finish_reason": "stop",
                }
            ],
        }


def create_proxy_app(config: AegisAgentConfig | None = None) -> FastAPI:
    """Build a standalone proxy app, optionally bound to an agent config."""
    from app.platform.proxy.router import router

    app = FastAPI(
        title="AegisAI Proxy",
        version=__version__,
        description="Universal runtime integration layer — route an agent through AegisAI.",
    )
    agent = config.id if config else DEFAULT_AGENT
    upstream = Upstream(config.upstream.url if config else None)
    adapter_name = config.upstream.adapter if config else "openai"

    app.state.proxy_config = config
    app.state.proxy_agent = agent
    app.state.proxy_upstream = upstream
    app.state.proxy_adapter = get_adapter(adapter_name)

    app.include_router(router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict:
        return {
            "status": "ok",
            "service": "aegis-proxy",
            "agent": agent,
            "upstream": upstream.url or "aegis-runtime (local)",
        }

    return app


def run(config: AegisAgentConfig | None, *, host: str, port: int, reload: bool = False) -> None:
    """Apply the config's policy and serve the proxy (used by ``aegis proxy``)."""
    import uvicorn

    if config is not None:
        config.apply_policy()
    uvicorn.run(create_proxy_app(config), host=host, port=port, reload=reload)

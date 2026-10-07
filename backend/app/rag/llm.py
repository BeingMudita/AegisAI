"""Minimal Ollama client for local LLM inference."""

from __future__ import annotations

import httpx

from app.config import get_settings

settings = get_settings()


class OllamaClient:
    """Thin async wrapper over the Ollama /api/generate endpoint."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.model_name
        self.timeout = timeout or settings.ollama_timeout

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Generate a completion for ``prompt`` (non-streaming)."""
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.base_url}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data.get("response", "").strip()

    async def health(self) -> bool:
        """Return True if the Ollama server is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except httpx.HTTPError:
            return False

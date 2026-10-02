"""AegisAI FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.router import api_router
from app.config import get_settings
from app.telemetry.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level, json_logs=settings.is_production)

# Fail closed: never serve production traffic with development secrets.
if settings.is_production and (insecure := settings.insecure_defaults()):
    raise RuntimeError(
        "Refusing to start in production with development defaults for: "
        + ", ".join(insecure)
        + ". Set them in the environment."
    )

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="A zero-trust security layer for autonomous AI agents.",
    debug=settings.debug and not settings.is_production,  # no tracebacks in prod
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    """Service banner."""
    return {"status": "ok", "service": settings.app_name}


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness/health probe."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": __version__,
        "environment": settings.environment,
    }

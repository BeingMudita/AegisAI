"""AegisAI FastAPI application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from app import __version__
from app.api.router import api_router
from app.config import get_settings
from app.platform.gateway_api import router as gateway_router
from app.platform.proxy import router as proxy_router
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


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.use_postgres:
        # Idempotent and lock-protected, so every worker may run it. The schema itself
        # comes from `python -m app.database.migrate` (the Docker image runs it first).
        from app.persistence.seed import seed_reference_data

        await run_in_threadpool(seed_reference_data)
    yield


app = FastAPI(
    lifespan=lifespan,
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
app.include_router(gateway_router)  # developer platform: /v1/secure/*
app.include_router(proxy_router)  # universal integration layer: /v1/proxy/*, /v1/chat/completions


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith(("/api/", "/v1/")):
        response.headers["Cache-Control"] = "no-store"
    return response


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

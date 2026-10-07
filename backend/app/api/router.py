"""Top-level API router — aggregates all endpoint groups under ``/api``."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    agents,
    approvals,
    auth,
    compliance,
    firewall,
    policies,
    redteam,
    retrieval,
    security_events,
    sessions,
    supply_chain,
    tools,
    trust,
    usage,
)

api_router = APIRouter(prefix="/api")

api_router.include_router(auth.router)
api_router.include_router(firewall.router)
api_router.include_router(agents.router)
api_router.include_router(sessions.router)
api_router.include_router(retrieval.router)
api_router.include_router(trust.router)
api_router.include_router(tools.router)
api_router.include_router(approvals.router)
api_router.include_router(redteam.router)
api_router.include_router(compliance.router)
api_router.include_router(policies.router)
api_router.include_router(security_events.router)
api_router.include_router(supply_chain.router)
api_router.include_router(usage.router)

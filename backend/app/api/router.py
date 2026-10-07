"""Top-level API router — aggregates all endpoint groups under ``/api``."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    adaptive,
    agents,
    approvals,
    attack_surface,
    auth,
    autopilot,
    compliance,
    firewall,
    gate,
    policies,
    redteam,
    registry,
    retrieval,
    scanner,
    security_events,
    sessions,
    supply_chain,
    threatintel,
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
api_router.include_router(scanner.router)
api_router.include_router(compliance.router)
api_router.include_router(policies.router)
api_router.include_router(security_events.router)
api_router.include_router(supply_chain.router)
api_router.include_router(usage.router)
api_router.include_router(registry.router)
api_router.include_router(gate.router)
api_router.include_router(adaptive.router)
api_router.include_router(autopilot.router)
api_router.include_router(attack_surface.router)
api_router.include_router(threatintel.router)

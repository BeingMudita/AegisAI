"""AegisAI — the developer-facing SDK.

    from aegisai import SecureAgent, AegisGuard, AegisMiddleware

A thin public surface over :mod:`app.platform`; see that package for the
implementation. Importing this requires the AegisAI backend on the path (it is,
when you run from the ``backend/`` directory or install the backend).
"""

from __future__ import annotations

from app.platform.policyfile import (
    AegisFile,
    ResolvedPosture,
    apply,
    lint,
    load_aegis_file,
)
from app.platform.sdk import (
    AegisGuard,
    AegisMiddleware,
    OutputScan,
    SecureAgent,
    SecureResult,
)

__all__ = [
    "SecureAgent",
    "AegisGuard",
    "AegisMiddleware",
    "SecureResult",
    "OutputScan",
    "AegisFile",
    "ResolvedPosture",
    "load_aegis_file",
    "apply",
    "lint",
]

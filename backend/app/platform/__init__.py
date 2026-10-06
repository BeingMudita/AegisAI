"""The AegisAI developer platform.

A thin layer that turns the AegisAI engines into something other AI agents can
plug into:

* :mod:`app.platform.policyfile` — ``aegis.yaml`` policy-as-code.
* :mod:`app.platform.sdk` — the Python SDK (``SecureAgent``, ``AegisGuard``,
  ``AegisMiddleware``), also re-exported from the top-level ``aegisai`` package.
* :mod:`app.platform.gateway_api` — the ``/v1/secure/*`` REST gateway.
* :mod:`app.platform.cli` — the ``aegis`` command-line tool.

Nothing here reimplements a security control; every module wraps the existing
firewall, trust engine, policy engine, tool gateway, DLP and agent runtime.
"""

from __future__ import annotations

from app.platform.policyfile import AegisFile, ResolvedPosture, apply, lint, load_aegis_file
from app.platform.sdk import AegisGuard, AegisMiddleware, SecureAgent, SecureResult

__all__ = [
    "AegisFile",
    "ResolvedPosture",
    "load_aegis_file",
    "apply",
    "lint",
    "SecureAgent",
    "AegisGuard",
    "AegisMiddleware",
    "SecureResult",
]

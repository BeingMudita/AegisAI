"""User roles for AegisAI role-based access control (RBAC)."""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    """The three AegisAI principal roles.

    - ``ADMIN``            — full control: manage users, policies, and config.
    - ``SECURITY_ANALYST`` — read security telemetry, review events, tune trust.
    - ``AGENT``            — an autonomous agent identity acting through the API.
    """

    ADMIN = "ADMIN"
    SECURITY_ANALYST = "SECURITY_ANALYST"
    AGENT = "AGENT"


# Convenience role groups for endpoint guards.
ALL_ROLES: tuple[Role, ...] = tuple(Role)
STAFF_ROLES: tuple[Role, ...] = (Role.ADMIN, Role.SECURITY_ANALYST)

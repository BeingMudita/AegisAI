"""Pydantic schemas for tenants and tenant-level policy."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

DEFAULT_TENANT = "default"
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]$|^[a-z0-9]$")


class TenantPolicy(BaseModel):
    """Org-wide guardrails that constrain *every* agent in the tenant.

    These compose with each agent's own policy by the most-restrictive-wins rules
    in :mod:`app.tenants.composition`:

    * ``allowed_tools`` — if non-empty, an agent may use only tools in this set
      (an org allow-list on top of each agent's own); empty means "no extra
      restriction, each agent's allow-list stands".
    * ``denied_tools`` — tools no agent in the tenant may use, whatever its own
      policy says (an org kill-switch).
    * ``allowed_domains`` — if non-empty, the only domains any agent may reach.
    * ``sensitive_data`` — categories the whole tenant treats as sensitive (added
      to every agent's own set).
    * ``max_delegation_depth`` — how many agent→agent hops an orchestration may chain.
    """

    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    sensitive_data: list[str] = Field(default_factory=list)
    max_delegation_depth: int = Field(default=3, ge=1, le=10)


class Tenant(BaseModel):
    """An isolation boundary that owns a set of agents and users."""

    slug: str = Field(description="URL-safe unique id, e.g. 'acme'.")
    name: str
    policy: TenantPolicy = Field(default_factory=TenantPolicy)

    @field_validator("slug")
    @classmethod
    def _valid_slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not _SLUG.match(v):
            raise ValueError("slug must be 1-40 chars, lowercase letters/digits/hyphens.")
        return v


class TenantSummary(BaseModel):
    """A tenant plus its membership counts (for the API)."""

    slug: str
    name: str
    policy: TenantPolicy
    agents: list[str]
    users: list[str]


class CreateTenantRequest(BaseModel):
    slug: str
    name: str
    policy: TenantPolicy = Field(default_factory=TenantPolicy)

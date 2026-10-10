"""Tenant store — tenants, their policies, and agent/user membership.

In memory mode everything lives in process, seeded with a single ``default``
tenant that owns the seed agents and users. With ``STORAGE_BACKEND=postgres`` the
:class:`app.persistence.tenants.PostgresTenantStore` reads the ``tenants`` table
and the ``tenant_id`` columns on ``agents`` / ``users``. Callers use this interface.
"""

from __future__ import annotations

import threading
from functools import lru_cache

from app.config import get_settings
from app.policies.engine import PolicyEngine
from app.policies.schemas import AgentPolicy
from app.policies.store import get_policy, list_policies
from app.tenants.composition import compose_policy
from app.tenants.schemas import DEFAULT_TENANT, Tenant, TenantPolicy, TenantSummary


class TenantExists(ValueError):
    """Raised when creating a tenant whose slug is already taken."""


class TenantStore:
    """In-memory tenants and membership (one API worker)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tenants: dict[str, Tenant] = {}
        self._agent_tenant: dict[str, str] = {}  # agent name (lower) -> slug
        self._user_tenant: dict[str, str] = {}  # username (lower) -> slug
        self._seed()

    def _seed(self) -> None:
        self._tenants[DEFAULT_TENANT] = Tenant(slug=DEFAULT_TENANT, name="Default organisation")
        for agent in ("FinanceAgent", "ResearchAgent"):
            self._agent_tenant[agent.lower()] = DEFAULT_TENANT
        for user in ("admin", "analyst", "agent"):
            self._user_tenant[user.lower()] = DEFAULT_TENANT

    # ------------------------------------------------------------- tenants
    def get_tenant(self, slug: str) -> Tenant | None:
        with self._lock:
            return self._tenants.get(slug.strip().lower())

    def list_tenants(self) -> list[Tenant]:
        with self._lock:
            return list(self._tenants.values())

    def create_tenant(self, tenant: Tenant) -> Tenant:
        with self._lock:
            if tenant.slug in self._tenants:
                raise TenantExists(f"Tenant '{tenant.slug}' already exists.")
            self._tenants[tenant.slug] = tenant
            return tenant

    def set_policy(self, slug: str, policy: TenantPolicy) -> Tenant:
        with self._lock:
            tenant = self._tenants.get(slug.strip().lower())
            if tenant is None:
                raise KeyError(slug)
            updated = tenant.model_copy(update={"policy": policy})
            self._tenants[updated.slug] = updated
            return updated

    # ---------------------------------------------------------- membership
    def assign_agent(self, agent: str, slug: str) -> None:
        with self._lock:
            if slug.strip().lower() not in self._tenants:
                raise KeyError(slug)
            self._agent_tenant[agent.strip().lower()] = slug.strip().lower()

    def assign_user(self, username: str, slug: str) -> None:
        with self._lock:
            if slug.strip().lower() not in self._tenants:
                raise KeyError(slug)
            self._user_tenant[username.strip().lower()] = slug.strip().lower()

    def tenant_of_agent(self, agent: str) -> str:
        with self._lock:
            return self._agent_tenant.get(agent.strip().lower(), DEFAULT_TENANT)

    def tenant_of_user(self, username: str) -> str:
        with self._lock:
            return self._user_tenant.get(username.strip().lower(), DEFAULT_TENANT)

    def agents_in_tenant(self, slug: str) -> list[str]:
        slug = slug.strip().lower()
        names = sorted({p.agent for p in list_policies()})
        return [a for a in names if self.tenant_of_agent(a) == slug]

    def users_in_tenant(self, slug: str) -> list[str]:
        slug = slug.strip().lower()
        with self._lock:
            return sorted(u for u, s in self._user_tenant.items() if s == slug)

    def clear(self) -> None:
        with self._lock:
            self._tenants.clear()
            self._agent_tenant.clear()
            self._user_tenant.clear()
        self._seed()

    # ------------------------------------------------------------- summary
    def summary(self, slug: str) -> TenantSummary | None:
        tenant = self.get_tenant(slug)
        if tenant is None:
            return None
        return TenantSummary(
            slug=tenant.slug,
            name=tenant.name,
            policy=tenant.policy,
            agents=self.agents_in_tenant(tenant.slug),
            users=self.users_in_tenant(tenant.slug),
        )


@lru_cache
def get_tenant_store() -> TenantStore:
    """The process-wide tenant store (Postgres-backed when configured)."""
    if get_settings().use_postgres:
        from app.persistence.tenants import PostgresTenantStore

        return PostgresTenantStore()
    return TenantStore()


def tenant_policy_for_agent(agent: str) -> TenantPolicy:
    """The policy of the tenant that owns ``agent`` (empty default if unknown)."""
    store = get_tenant_store()
    tenant = store.get_tenant(store.tenant_of_agent(agent))
    return tenant.policy if tenant else TenantPolicy()


def effective_policy(agent: str) -> AgentPolicy | None:
    """``agent``'s own policy folded into its tenant's policy, or None if the agent
    has no policy. This is what the gateway and runtime enforce."""
    base = get_policy(agent)
    if base is None:
        return None
    return compose_policy(tenant_policy_for_agent(agent), base)


def effective_engine(agent: str) -> PolicyEngine | None:
    """A :class:`PolicyEngine` over the agent's effective (tenant-composed) policy."""
    policy = effective_policy(agent)
    return PolicyEngine(policy) if policy is not None else None

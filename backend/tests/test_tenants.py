"""Tenant isolation and policy composition (multi-agent orchestration groundwork)."""

from __future__ import annotations

import pytest

from app.policies.schemas import AgentPolicy
from app.tenants.composition import compose_policy
from app.tenants.schemas import DEFAULT_TENANT, Tenant, TenantPolicy
from app.tenants.store import effective_policy, get_tenant_store


# ----------------------------------------------------------- composition
def test_empty_tenant_policy_leaves_the_agent_policy_unchanged() -> None:
    agent = AgentPolicy(
        agent="A", allowed_tools=["x", "y"], allowed_domains=["company.com"], sensitive_data=["pii"]
    )
    composed = compose_policy(TenantPolicy(), agent)
    assert composed.allowed_tools == ["x", "y"]
    assert composed.allowed_domains == ["company.com"]
    assert composed.sensitive_data == ["pii"]


def test_tenant_allow_list_intersects_tools() -> None:
    agent = AgentPolicy(agent="A", allowed_tools=["read_database", "send_email", "web_fetch"])
    tenant = TenantPolicy(allowed_tools=["read_database", "web_fetch"])
    assert compose_policy(tenant, agent).allowed_tools == ["read_database", "web_fetch"]


def test_tenant_denied_tools_win_over_agent_allow() -> None:
    agent = AgentPolicy(agent="A", allowed_tools=["read_database", "send_email"])
    tenant = TenantPolicy(denied_tools=["send_email"])
    composed = compose_policy(tenant, agent)
    assert "send_email" not in composed.allowed_tools
    assert "send_email" in composed.blocked_tools


def test_tenant_domains_restrict_the_agent() -> None:
    agent = AgentPolicy(agent="A", allowed_domains=["company.com", "evil.com", "sub.company.com"])
    tenant = TenantPolicy(allowed_domains=["company.com"])
    composed = compose_policy(tenant, agent)
    assert composed.allowed_domains == ["company.com", "sub.company.com"]  # subdomain kept


def test_sensitive_categories_are_unioned() -> None:
    agent = AgentPolicy(agent="A", sensitive_data=["pii"])
    tenant = TenantPolicy(sensitive_data=["secrets"])
    assert compose_policy(tenant, agent).sensitive_data == ["pii", "secrets"]


# ------------------------------------------------------------- the store
def test_default_tenant_owns_the_seed_agents() -> None:
    store = get_tenant_store()
    assert store.tenant_of_agent("FinanceAgent") == DEFAULT_TENANT
    assert "FinanceAgent" in store.agents_in_tenant(DEFAULT_TENANT)


def test_isolation_agents_do_not_leak_across_tenants() -> None:
    store = get_tenant_store()
    store.create_tenant(Tenant(slug="acme", name="Acme"))
    store.assign_agent("ResearchAgent", "acme")
    assert store.tenant_of_agent("ResearchAgent") == "acme"
    assert "ResearchAgent" not in store.agents_in_tenant(DEFAULT_TENANT)
    assert store.agents_in_tenant("acme") == ["ResearchAgent"]


def test_effective_policy_applies_the_tenant_guardrails() -> None:
    store = get_tenant_store()
    store.create_tenant(
        Tenant(slug="locked", name="Locked", policy=TenantPolicy(denied_tools=["send_email"]))
    )
    store.assign_agent("FinanceAgent", "locked")
    eff = effective_policy("FinanceAgent")
    assert eff is not None
    assert "send_email" in eff.blocked_tools and "send_email" not in eff.allowed_tools
    # read_database is still allowed by both the agent and the tenant.
    assert "read_database" in eff.allowed_tools


def test_create_duplicate_tenant_rejected() -> None:
    from app.tenants.store import TenantExists

    store = get_tenant_store()
    store.create_tenant(Tenant(slug="dup", name="Dup"))
    with pytest.raises(TenantExists):
        store.create_tenant(Tenant(slug="dup", name="Dup again"))

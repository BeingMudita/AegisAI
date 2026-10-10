"""Policy composition — fold a tenant's policy into an agent's policy.

Pure functions, no I/O. The result is a plain :class:`~app.policies.schemas.AgentPolicy`,
so the existing :class:`~app.policies.engine.PolicyEngine` evaluates the *effective*
policy with no change — tenant rules add constraints, they never add a new code path.

Most-restrictive-wins throughout:

* a tool must be allowed by the agent, and (if the tenant sets an allow-list) by the
  tenant, and must not be denied by either;
* a domain must be allowed by the agent, and (if the tenant sets an allow-list) sit
  within a tenant-allowed domain;
* a data category is sensitive if either the agent or the tenant marks it so.
"""

from __future__ import annotations

from app.policies.schemas import AgentPolicy
from app.tenants.schemas import TenantPolicy


def _domain_within(host: str, allowed: list[str]) -> bool:
    host = host.lower().strip()
    return any(host == a.lower().strip() or host.endswith("." + a.lower().strip()) for a in allowed)


def compose_policy(tenant: TenantPolicy, agent: AgentPolicy) -> AgentPolicy:
    """The effective policy for ``agent`` inside a tenant governed by ``tenant``."""
    denied = set(agent.blocked_tools) | set(tenant.denied_tools)

    allowed_tools = [t for t in agent.allowed_tools if t not in denied]
    if tenant.allowed_tools:
        org_allowed = set(tenant.allowed_tools)
        allowed_tools = [t for t in allowed_tools if t in org_allowed]

    if tenant.allowed_domains:
        allowed_domains = [
            d for d in agent.allowed_domains if _domain_within(d, tenant.allowed_domains)
        ]
    else:
        allowed_domains = list(agent.allowed_domains)

    return AgentPolicy(
        agent=agent.agent,
        allowed_tools=allowed_tools,
        blocked_tools=sorted(denied),
        allowed_domains=allowed_domains,
        sensitive_data=sorted(set(agent.sensitive_data) | set(tenant.sensitive_data)),
    )

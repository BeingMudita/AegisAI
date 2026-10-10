"""Tenants — organisation boundaries and the policy they impose on their agents.

A tenant is an isolation boundary: its users see and act on only its own agents,
policies, sessions, events and tool requests. Every agent belongs to exactly one
tenant, and the tenant's :class:`~app.tenants.schemas.TenantPolicy` composes with
each agent's own policy (most-restrictive-wins) to give the *effective* policy the
gateway and runtime enforce. See :mod:`app.tenants.composition`.
"""

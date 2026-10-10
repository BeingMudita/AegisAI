"""Seed reference data into Postgres: users, agents, agent policies, tool definitions.

Idempotent and safe to run from several workers at once (an advisory lock
serializes it). Existing users, agents and policies are never overwritten — an
administrator's later changes win over the files they were seeded from. Tool
definitions are the exception: they mirror ``default_policies.yaml`` and are
refreshed from it on every seed.
"""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from app.auth.roles import Role
from app.auth.security import hash_password
from app.config import get_settings
from app.database.models import Agent, Policy, Tenant, ToolDefinition, User
from app.database.sync import transaction
from app.policies.config import get_global_config
from app.policies.store import example_policies
from app.tenants.schemas import DEFAULT_TENANT

_SEED_LOCK = 0x5EED_A1E5


def seed_reference_data() -> None:
    settings = get_settings()
    accounts = [
        ("admin", settings.seed_admin_password, Role.ADMIN),
        ("analyst", settings.seed_analyst_password, Role.SECURITY_ANALYST),
        ("agent", settings.seed_agent_password, Role.AGENT),
    ]
    with transaction() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _SEED_LOCK})

        # The default tenant owns every seeded user and agent (migration 0006 creates
        # it; create it here too so seeding a fresh in-test database is self-contained).
        default_tid = db.scalar(select(Tenant.id).where(Tenant.slug == DEFAULT_TENANT))
        if default_tid is None:
            tenant = Tenant(slug=DEFAULT_TENANT, name="Default organisation", policy={})
            db.add(tenant)
            db.flush()
            default_tid = tenant.id

        existing = set(db.scalars(select(User.username)))
        for username, password, role in accounts:
            if username not in existing:  # hash only what's missing (bcrypt is slow)
                db.add(
                    User(
                        username=username,
                        hashed_password=hash_password(password),
                        role=role,
                        tenant_id=default_tid,
                    )
                )

        for policy in example_policies():
            db.execute(
                insert(Agent)
                .values(name=policy.agent, tenant_id=default_tid)
                .on_conflict_do_nothing()
            )
            agent_id = db.scalar(select(Agent.id).where(Agent.name == policy.agent))
            has_policy = db.scalar(
                select(Policy.id).where((Policy.agent_id == agent_id) & Policy.is_active)
            )
            if has_policy is None:
                db.add(
                    Policy(
                        name=policy.agent,
                        agent_id=agent_id,
                        allowed_tools=policy.allowed_tools,
                        blocked_tools=policy.blocked_tools,
                        allowed_domains=policy.allowed_domains,
                        sensitive_data=policy.sensitive_data,
                        raw=policy.model_dump(),
                        is_active=True,
                    )
                )

        # tool_definitions is a read-only mirror of default_policies.yaml (the source of
        # truth the gateway reads), kept for SQL reporting — so it is overwritten, not
        # just inserted, to keep it in step with the file.
        for tool in get_global_config().tools:
            values = {
                "description": tool.description,
                "risk_level": tool.risk_level,
                "is_enabled": tool.allowed,
                "requires_approval": tool.requires_approval,
            }
            db.execute(
                insert(ToolDefinition)
                .values(name=tool.name, **values)
                .on_conflict_do_update(index_elements=[ToolDefinition.name], set_=values)
            )

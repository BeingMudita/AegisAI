"""Seed reference data into Postgres: users, agents, agent policies, tool definitions.

Idempotent and safe to run from several workers at once (an advisory lock
serializes it). Existing rows are never overwritten — an administrator's later
changes win over the files they were seeded from.
"""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from app.auth.roles import Role
from app.auth.security import hash_password
from app.config import get_settings
from app.database.models import Agent, Policy, ToolDefinition, User
from app.database.sync import transaction
from app.policies.config import get_global_config
from app.policies.store import example_policies

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

        existing = set(db.scalars(select(User.username)))
        for username, password, role in accounts:
            if username not in existing:  # hash only what's missing (bcrypt is slow)
                db.add(User(username=username, hashed_password=hash_password(password), role=role))

        for policy in example_policies():
            db.execute(insert(Agent).values(name=policy.agent).on_conflict_do_nothing())
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

        for tool in get_global_config().tools:
            db.execute(
                insert(ToolDefinition)
                .values(
                    name=tool.name,
                    description=tool.description,
                    risk_level=tool.risk_level,
                    is_enabled=tool.allowed,
                    requires_approval=False,
                )
                .on_conflict_do_nothing(index_elements=[ToolDefinition.name])
            )

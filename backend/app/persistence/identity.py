"""Users and agent policies read from Postgres."""

from __future__ import annotations

from sqlalchemy import Select, func, select

from app.auth.schemas import UserInDB
from app.database.models import Agent, Policy, User
from app.database.sync import transaction
from app.policies.schemas import AgentPolicy


def get_db_user(username: str) -> UserInDB | None:
    with transaction() as db:
        row = db.scalars(select(User).where(User.username == username)).first()
        if row is None:
            return None
        return UserInDB(
            username=row.username,
            role=row.role,
            disabled=row.disabled,
            hashed_password=row.hashed_password,
        )


def _policy(row: Policy, agent: str) -> AgentPolicy:
    return AgentPolicy(
        agent=agent,
        allowed_tools=list(row.allowed_tools or []),
        blocked_tools=list(row.blocked_tools or []),
        allowed_domains=list(row.allowed_domains or []),
        sensitive_data=list(row.sensitive_data or []),
    )


def _active() -> Select[tuple[Policy, str]]:
    return (
        select(Policy, Agent.name).join(Agent, Agent.id == Policy.agent_id).where(Policy.is_active)
    )


def list_db_policies() -> list[AgentPolicy]:
    with transaction() as db:
        return [_policy(row, name) for row, name in db.execute(_active().order_by(Agent.name))]


def get_db_policy(agent: str) -> AgentPolicy | None:
    with transaction() as db:
        hit = db.execute(_active().where(func.lower(Agent.name) == agent.lower()).limit(1)).first()
        return _policy(hit[0], hit[1]) if hit else None

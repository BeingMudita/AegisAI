"""Tenant store backed by Postgres — tenants and the ``tenant_id`` membership columns.

Mirrors :class:`app.tenants.store.TenantStore`. Agent and user membership lives on
``agents.tenant_id`` / ``users.tenant_id``; an agent or user with no tenant (or an
unknown name) belongs to the ``default`` tenant, matching the memory store.
"""

from __future__ import annotations

from sqlalchemy import delete, func, select, update

from app.database.models import Agent, User
from app.database.models import Tenant as TenantRow
from app.database.sync import transaction
from app.tenants.schemas import DEFAULT_TENANT, Tenant, TenantPolicy, TenantSummary
from app.tenants.store import TenantExists


def _to_tenant(row: TenantRow) -> Tenant:
    policy = TenantPolicy.model_validate(row.policy or {})
    return Tenant(slug=row.slug, name=row.name, policy=policy)


class PostgresTenantStore:
    """Tenants and membership in Postgres (shared across workers)."""

    # ------------------------------------------------------------- tenants
    def get_tenant(self, slug: str) -> Tenant | None:
        slug = slug.strip().lower()
        with transaction() as db:
            row = db.scalars(select(TenantRow).where(TenantRow.slug == slug)).first()
            return _to_tenant(row) if row else None

    def list_tenants(self) -> list[Tenant]:
        with transaction() as db:
            return [_to_tenant(r) for r in db.scalars(select(TenantRow).order_by(TenantRow.slug))]

    def create_tenant(self, tenant: Tenant) -> Tenant:
        with transaction() as db:
            if db.scalar(select(TenantRow.id).where(TenantRow.slug == tenant.slug)) is not None:
                raise TenantExists(f"Tenant '{tenant.slug}' already exists.")
            db.add(
                TenantRow(slug=tenant.slug, name=tenant.name, policy=tenant.policy.model_dump())
            )
        return tenant

    def set_policy(self, slug: str, policy: TenantPolicy) -> Tenant:
        slug = slug.strip().lower()
        with transaction() as db:
            row = db.scalars(select(TenantRow).where(TenantRow.slug == slug)).first()
            if row is None:
                raise KeyError(slug)
            row.policy = policy.model_dump()
            return Tenant(slug=row.slug, name=row.name, policy=policy)

    # ---------------------------------------------------------- membership
    def _tenant_id(self, db, slug: str):  # type: ignore[no-untyped-def]
        tid = db.scalar(select(TenantRow.id).where(TenantRow.slug == slug.strip().lower()))
        if tid is None:
            raise KeyError(slug)
        return tid

    def assign_agent(self, agent: str, slug: str) -> None:
        with transaction() as db:
            tid = self._tenant_id(db, slug)
            name = agent.strip()
            existing = db.scalar(select(Agent.id).where(func.lower(Agent.name) == name.lower()))
            if existing is None:
                db.add(Agent(name=name, tenant_id=tid))
            else:
                db.execute(update(Agent).where(Agent.id == existing).values(tenant_id=tid))

    def assign_user(self, username: str, slug: str) -> None:
        with transaction() as db:
            tid = self._tenant_id(db, slug)
            db.execute(
                update(User)
                .where(func.lower(User.username) == username.strip().lower())
                .values(tenant_id=tid)
            )

    def tenant_of_agent(self, agent: str) -> str:
        with transaction() as db:
            slug = db.scalar(
                select(TenantRow.slug)
                .select_from(Agent)
                .join(TenantRow, TenantRow.id == Agent.tenant_id)
                .where(func.lower(Agent.name) == agent.strip().lower())
            )
        return slug or DEFAULT_TENANT

    def tenant_of_user(self, username: str) -> str:
        with transaction() as db:
            slug = db.scalar(
                select(TenantRow.slug)
                .select_from(User)
                .join(TenantRow, TenantRow.id == User.tenant_id)
                .where(func.lower(User.username) == username.strip().lower())
            )
        return slug or DEFAULT_TENANT

    def agents_in_tenant(self, slug: str) -> list[str]:
        slug = slug.strip().lower()
        with transaction() as db:
            rows = db.execute(
                select(Agent.name, TenantRow.slug)
                .outerjoin(TenantRow, TenantRow.id == Agent.tenant_id)
                .order_by(Agent.name)
            )
            return [name for name, s in rows if (s or DEFAULT_TENANT) == slug]

    def users_in_tenant(self, slug: str) -> list[str]:
        slug = slug.strip().lower()
        with transaction() as db:
            rows = db.execute(
                select(User.username, TenantRow.slug)
                .outerjoin(TenantRow, TenantRow.id == User.tenant_id)
                .order_by(User.username)
            )
            return [name for name, s in rows if (s or DEFAULT_TENANT) == slug]

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

    def clear(self) -> None:
        """Reset to the seeded state (tests): keep only 'default' with an empty
        policy, and move every agent/user back into it."""
        with transaction() as db:
            db.execute(delete(TenantRow).where(TenantRow.slug != DEFAULT_TENANT))
            row = db.scalars(select(TenantRow).where(TenantRow.slug == DEFAULT_TENANT)).first()
            if row is None:
                row = TenantRow(slug=DEFAULT_TENANT, name="Default organisation", policy={})
                db.add(row)
                db.flush()
            else:
                row.policy = {}
            db.execute(update(Agent).values(tenant_id=row.id))
            db.execute(update(User).values(tenant_id=row.id))

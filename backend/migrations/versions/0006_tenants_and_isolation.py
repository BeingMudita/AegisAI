"""tenants and tenant isolation (multi-agent policy orchestration)

* ``tenants`` — an organisation boundary with a composed policy (JSONB).
* ``users.tenant_id`` / ``agents.tenant_id`` — membership (FK, SET NULL on delete).
* A 'default' tenant is created and every existing user and agent is backfilled
  into it, so nothing loses its home.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-10 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
    )
    op.create_index(op.f("ix_tenants_slug"), "tenants", ["slug"], unique=True)

    op.add_column("users", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_users_tenant_id"), "users", ["tenant_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_users_tenant_id_tenants"),
        "users",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("agents", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_agents_tenant_id"), "agents", ["tenant_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_agents_tenant_id_tenants"),
        "agents",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Seed the default tenant and move every existing user/agent into it.
    op.execute(
        "INSERT INTO tenants (id, slug, name, policy) "
        "VALUES (gen_random_uuid(), 'default', 'Default organisation', '{}'::jsonb)"
    )
    op.execute(
        "UPDATE users SET tenant_id = (SELECT id FROM tenants WHERE slug = 'default') "
        "WHERE tenant_id IS NULL"
    )
    op.execute(
        "UPDATE agents SET tenant_id = (SELECT id FROM tenants WHERE slug = 'default') "
        "WHERE tenant_id IS NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("fk_agents_tenant_id_tenants"), "agents", type_="foreignkey")
    op.drop_index(op.f("ix_agents_tenant_id"), table_name="agents")
    op.drop_column("agents", "tenant_id")
    op.drop_constraint(op.f("fk_users_tenant_id_tenants"), "users", type_="foreignkey")
    op.drop_index(op.f("ix_users_tenant_id"), table_name="users")
    op.drop_column("users", "tenant_id")
    op.drop_index(op.f("ix_tenants_slug"), table_name="tenants")
    op.drop_table("tenants")

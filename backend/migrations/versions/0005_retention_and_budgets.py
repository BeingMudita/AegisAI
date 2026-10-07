"""retention and quotas: session expiry, per-principal budgets

* ``session_status`` gains ``EXPIRED`` — a session idle for longer than
  SESSION_IDLE_MINUTES refuses further messages.
* ``agent_sessions.last_activity_at`` — when the last turn finished (backfilled
  from the turns); drives idle expiry.
* ``usage_budgets`` — turns, tokens and cost per principal per UTC day.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Allowed inside a transaction since PostgreSQL 12 (the value is first used later).
    op.execute("ALTER TYPE session_status ADD VALUE IF NOT EXISTS 'EXPIRED'")

    op.add_column(
        'agent_sessions',
        sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f('ix_agent_sessions_last_activity_at'), 'agent_sessions', ['last_activity_at']
    )
    op.execute(
        """
        UPDATE agent_sessions s
        SET last_activity_at = COALESCE(
            (SELECT max(t.created_at) FROM agent_turns t WHERE t.session_id = s.id),
            s.started_at
        )
        """
    )

    op.create_table(
        'usage_budgets',
        sa.Column('principal', sa.String(length=128), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('turns', sa.Integer(), nullable=False),
        sa.Column('prompt_tokens', sa.BigInteger(), nullable=False),
        sa.Column('completion_tokens', sa.BigInteger(), nullable=False),
        sa.Column('tokens', sa.BigInteger(), nullable=False),
        sa.Column('cost_usd', sa.Float(), nullable=False),
        sa.Column('exhausted_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('principal', 'day', name=op.f('pk_usage_budgets')),
    )
    op.create_index(op.f('ix_usage_budgets_day'), 'usage_budgets', ['day'])


def downgrade() -> None:
    """Downgrade schema.

    PostgreSQL can't drop an enum value; expired sessions become CLOSED and the
    unused ``EXPIRED`` label stays on the type.
    """
    op.drop_index(op.f('ix_usage_budgets_day'), table_name='usage_budgets')
    op.drop_table('usage_budgets')
    op.drop_index(op.f('ix_agent_sessions_last_activity_at'), table_name='agent_sessions')
    op.drop_column('agent_sessions', 'last_activity_at')
    op.execute("UPDATE agent_sessions SET status = 'CLOSED' WHERE status = 'EXPIRED'")

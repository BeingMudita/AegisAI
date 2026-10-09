"""requester on tool requests, case-insensitive lookup indexes, rate-limit index

* ``tool_requests.requested_by`` — the principal an agent acted for; trust is scoped
  to that principal and re-checked against it at approval time.
* ``lower(...)`` indexes for the case-insensitive lookups the stores make (agents by
  name, events and tool requests by agent, document sources by name).
* ``rate_limit_hits``: one (key, at) index replaces the key-only index, matching the
  limiter's "hits for this key inside the window" query.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('tool_requests', sa.Column('requested_by', sa.String(length=64), nullable=True))
    op.create_index('ix_tool_requests_agent_lower', 'tool_requests', [sa.text('lower(agent)')])
    op.create_index('ix_security_events_actor_lower', 'security_events', [sa.text('lower(actor)')])
    op.create_index('ix_agents_name_lower', 'agents', [sa.text('lower(name)')])
    op.create_index(
        'ix_document_sources_name_lower', 'document_sources', [sa.text('lower(name)')]
    )
    op.drop_index(op.f('ix_rate_limit_hits_key'), table_name='rate_limit_hits')
    op.create_index('ix_rate_limit_hits_key_at', 'rate_limit_hits', ['key', 'at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_rate_limit_hits_key_at', table_name='rate_limit_hits')
    op.create_index(op.f('ix_rate_limit_hits_key'), 'rate_limit_hits', ['key'], unique=False)
    op.drop_index('ix_document_sources_name_lower', table_name='document_sources')
    op.drop_index('ix_agents_name_lower', table_name='agents')
    op.drop_index('ix_security_events_actor_lower', table_name='security_events')
    op.drop_index('ix_tool_requests_agent_lower', table_name='tool_requests')
    op.drop_column('tool_requests', 'requested_by')

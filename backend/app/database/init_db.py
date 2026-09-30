"""Initialize the database: enable pgvector and create all tables.

Local-first bootstrap. Run from the ``backend`` directory:

    python -m app.database.init_db

For production, prefer Alembic migrations over ``create_all``.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.database.models import Base  # noqa: F401  (registers all tables)
from app.database.session import get_engine


async def init_db() -> None:
    """Enable the pgvector extension and create all tables."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("✅ Database initialized: pgvector enabled, tables created.")


if __name__ == "__main__":
    asyncio.run(init_db())

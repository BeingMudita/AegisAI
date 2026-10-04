"""Synchronous database access for the persistent stores.

The stores are called from synchronous code — LangGraph nodes, the tool
gateway, background ingestion threads — so they use a regular (psycopg2)
engine with a connection pool rather than the async engine in ``session.py``.
Every store operation runs in its own short transaction via :func:`transaction`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.config import get_settings


@lru_cache
def get_sync_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.sync_database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_size,
        future=True,
    )


@contextmanager
def transaction() -> Iterator[Session]:
    """A session whose work is committed on success and rolled back on error."""
    with Session(get_sync_engine(), expire_on_commit=False) as session, session.begin():
        yield session

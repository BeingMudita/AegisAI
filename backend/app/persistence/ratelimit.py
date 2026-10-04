"""A rolling-window rate limiter shared by every API worker (``rate_limit_hits``).

Each attempt for a key runs in one transaction holding a transaction-scoped
advisory lock on that key, so concurrent workers count it exactly: expired hits
are pruned, the window is counted, and the new hit is recorded only if allowed.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, text

from app.database.models import RateLimitHit
from app.database.sync import transaction


class PostgresRateLimiter:
    def try_acquire(self, key: str, *, limit: int, window_seconds: int) -> int:
        """Record an attempt for ``key``; 0 if allowed, else seconds until one is."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(seconds=window_seconds)
        with transaction() as db:
            db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": key})
            db.execute(
                delete(RateLimitHit).where((RateLimitHit.key == key) & (RateLimitHit.at <= start))
            )
            count, oldest = db.execute(
                select(func.count(), func.min(RateLimitHit.at)).where(RateLimitHit.key == key)
            ).one()
            if count >= limit:
                return max(
                    1, math.ceil((oldest + timedelta(seconds=window_seconds) - now).total_seconds())
                )
            db.add(RateLimitHit(key=key, at=now))
            return 0

    def clear(self, prefix: str = "") -> None:
        with transaction() as db:
            db.execute(delete(RateLimitHit).where(RateLimitHit.key.startswith(prefix)))


class PostgresLoginLimiter:
    """Same interface as :class:`app.auth.limiter.LoginLimiter`, shared across workers."""

    def __init__(self, limit: int = 10, window: int = 60) -> None:
        self.limit, self.window = limit, window
        self._limiter = PostgresRateLimiter()

    def retry_after(self, peer: str) -> int:
        return self._limiter.try_acquire(
            f"login:{peer}", limit=self.limit, window_seconds=self.window
        )

    def clear(self) -> None:
        self._limiter.clear("login:")

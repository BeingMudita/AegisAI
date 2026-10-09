"""A rolling-window rate limiter shared by every API worker (``rate_limit_hits``).

Each attempt for a key runs in one transaction holding a transaction-scoped
advisory lock on that key, so concurrent workers count it exactly: expired hits
are pruned, the window is counted, and the new hit is recorded only if allowed.

Keys that are never seen again (one-off client addresses, mistyped usernames)
would leave their rows behind, so each worker also sweeps every hit older than
``RETENTION`` once every few minutes.
"""

from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.database.models import RateLimitHit
from app.database.sync import transaction

RETENTION = timedelta(hours=1)  # longer than any limiter window
SWEEP_INTERVAL = 300.0  # seconds between sweeps, per worker


class PostgresRateLimiter:
    _sweep_lock = threading.Lock()
    _last_sweep = 0.0

    def _sweep(self) -> None:
        with PostgresRateLimiter._sweep_lock:
            now = time.monotonic()
            if now - PostgresRateLimiter._last_sweep < SWEEP_INTERVAL:
                return
            PostgresRateLimiter._last_sweep = now
        cutoff = datetime.now(timezone.utc) - RETENTION
        with transaction() as db:
            db.execute(delete(RateLimitHit).where(RateLimitHit.at < cutoff))

    def _window(
        self, db: Session, key: str, window_seconds: int, now: datetime
    ) -> tuple[int, datetime]:
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": key})
        start = now - timedelta(seconds=window_seconds)
        db.execute(
            delete(RateLimitHit).where((RateLimitHit.key == key) & (RateLimitHit.at <= start))
        )
        count, oldest = db.execute(
            select(func.count(), func.min(RateLimitHit.at)).where(RateLimitHit.key == key)
        ).one()
        return count, oldest

    @staticmethod
    def _wait(oldest: datetime, window_seconds: int, now: datetime) -> int:
        return max(1, math.ceil((oldest + timedelta(seconds=window_seconds) - now).total_seconds()))

    def try_acquire(self, key: str, *, limit: int, window_seconds: int) -> int:
        """Record an attempt for ``key``; 0 if allowed, else seconds until one is."""
        self._sweep()
        now = datetime.now(timezone.utc)
        with transaction() as db:
            count, oldest = self._window(db, key, window_seconds, now)
            if count >= limit:
                return self._wait(oldest, window_seconds, now)
            db.add(RateLimitHit(key=key, at=now))
            return 0

    def peek(self, key: str, *, limit: int, window_seconds: int) -> int:
        """Seconds until ``key`` may try again (0 = allowed), without recording a hit."""
        now = datetime.now(timezone.utc)
        with transaction() as db:
            count, oldest = self._window(db, key, window_seconds, now)
            return self._wait(oldest, window_seconds, now) if count >= limit else 0

    def clear(self, prefix: str = "") -> None:
        with transaction() as db:
            db.execute(delete(RateLimitHit).where(RateLimitHit.key.startswith(prefix)))


class PostgresLoginLimiter:
    """Same interface as :class:`app.auth.limiter.LoginLimiter`, shared across workers."""

    def __init__(self, name: str = "login", *, limit: int = 10, window: int = 60) -> None:
        self.prefix, self.limit, self.window = f"{name}:", limit, window
        self._limiter = PostgresRateLimiter()

    def retry_after(self, key: str) -> int:
        return self._limiter.try_acquire(
            self.prefix + key, limit=self.limit, window_seconds=self.window
        )

    def blocked_for(self, key: str) -> int:
        return self._limiter.peek(self.prefix + key, limit=self.limit, window_seconds=self.window)

    def clear(self) -> None:
        self._limiter.clear(self.prefix)

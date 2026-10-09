"""Login throttles: bounded and process-local in memory mode, shared through Postgres
otherwise. Still put a shared limiter at the production edge.

Two limits apply to sign-in:

* ``login_limiter``   — every attempt, per client address (stops spraying from one host);
* ``account_limiter`` — failed attempts, per username (stops a distributed guessing run
  against one account, without letting one address lock out everybody).
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.persistence.ratelimit import PostgresLoginLimiter


class LoginLimiter:
    def __init__(self, limit: int = 10, window: int = 60, capacity: int = 4096) -> None:
        self.limit, self.window, self.capacity = limit, window, capacity
        self._attempts: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        for key in list(self._attempts):
            attempts = self._attempts[key]
            while attempts and attempts[0] <= now - self.window:
                attempts.popleft()
            if not attempts:
                del self._attempts[key]

    def _wait(self, key: str, now: float) -> int:
        attempts = self._attempts.get(key)
        if attempts and len(attempts) >= self.limit:
            return max(1, math.ceil(attempts[0] + self.window - now))
        return 0

    def retry_after(self, key: str) -> int:
        """Reserve an attempt atomically, or return seconds until another is allowed."""
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            if key not in self._attempts and len(self._attempts) >= self.capacity:
                return self.window
            if wait := self._wait(key, now):
                return wait
            self._attempts.setdefault(key, deque()).append(now)
            return 0

    def blocked_for(self, key: str) -> int:
        """Seconds until ``key`` may try again (0 = allowed), without recording anything."""
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            return self._wait(key, now)

    def clear(self) -> None:
        with self._lock:
            self._attempts.clear()


def _make_limiter(name: str, limit: int, window: int) -> "LoginLimiter | PostgresLoginLimiter":
    from app.config import get_settings

    if get_settings().use_postgres:
        from app.persistence.ratelimit import PostgresLoginLimiter

        return PostgresLoginLimiter(name, limit=limit, window=window)  # shared by every worker
    return LoginLimiter(limit=limit, window=window)


login_limiter = _make_limiter("login", limit=10, window=60)
account_limiter = _make_limiter("account", limit=20, window=15 * 60)


def clear_login_limits() -> None:
    login_limiter.clear()
    account_limiter.clear()

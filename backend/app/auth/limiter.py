"""Login throttle: bounded and process-local in memory mode, shared through Postgres
otherwise. Still put a shared limiter at the production edge."""

import math
import threading
import time
from collections import deque


class LoginLimiter:
    def __init__(self, limit: int = 10, window: int = 60, capacity: int = 4096) -> None:
        self.limit, self.window, self.capacity = limit, window, capacity
        self._attempts: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def retry_after(self, peer: str) -> int:
        """Reserve an attempt atomically, or return seconds until another is allowed."""
        now = time.monotonic()
        with self._lock:
            for key in list(self._attempts):
                attempts = self._attempts[key]
                while attempts and attempts[0] <= now - self.window:
                    attempts.popleft()
                if not attempts:
                    del self._attempts[key]
            if peer not in self._attempts and len(self._attempts) >= self.capacity:
                return self.window
            attempts = self._attempts.setdefault(peer, deque())
            if len(attempts) >= self.limit:
                return max(1, math.ceil(attempts[0] + self.window - now))
            attempts.append(now)
            return 0

    def clear(self) -> None:
        with self._lock:
            self._attempts.clear()


def _make_limiter():  # type: ignore[no-untyped-def]
    from app.config import get_settings

    if get_settings().use_postgres:
        from app.persistence.ratelimit import PostgresLoginLimiter

        return PostgresLoginLimiter()  # shared by every API worker
    return LoginLimiter()


login_limiter = _make_limiter()

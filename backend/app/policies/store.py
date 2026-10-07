"""Policy store — loads agent policies.

In memory mode policies come from the JSON files in ``app/policies/examples``.
With ``STORAGE_BACKEND=postgres`` they are read from the ``policies`` table
(seeded from those same files on first start). Keeping the lookup behind this
module means the API and engine don't change when the backing store does.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import TypeVar

from app.config import get_settings
from app.policies.schemas import AgentPolicy

_EXAMPLES_DIR = Path(__file__).parent / "examples"
_T = TypeVar("_T")

# Postgres mode: one agent turn reads the agent's policy several times (retrieval,
# tool catalog, every gateway check, the output guard), so reads are reused for
# POLICY_CACHE_SECONDS. Policies change rarely; a change is live within that time.
_cache: dict[str, tuple[float, object]] = {}
_cache_lock = threading.Lock()
_CACHE_MAX_KEYS = 1024


def _cached(key: str, load: Callable[[], _T]) -> _T:
    ttl = get_settings().policy_cache_seconds
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]  # type: ignore[return-value]
    value = load()
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX_KEYS:  # lookups of made-up agent names add keys too
            _cache.clear()
        _cache[key] = (now, value)
    return value


def clear_policy_cache() -> None:
    """Forget cached policies (tests, or right after editing the policies table)."""
    with _cache_lock:
        _cache.clear()


# Runtime overrides registered by the developer platform (policy-as-code / SDK).
# They take precedence over the file- and DB-backed policies so an agent defined
# in an ``aegis.yaml`` is visible everywhere ``get_policy`` is consulted (the
# gateway, the runtime, the API) without touching the backing store.
_overrides: dict[str, AgentPolicy] = {}


def register_policy(policy: AgentPolicy) -> None:
    """Register (or replace) an agent policy at runtime, keyed by agent name."""
    _overrides[policy.agent.lower()] = policy


def clear_overrides() -> None:
    """Drop every runtime-registered policy (used by tests)."""
    _overrides.clear()


@lru_cache
def _load_all() -> dict[str, AgentPolicy]:
    """Load and cache every policy JSON keyed by agent name (lowercased)."""
    policies: dict[str, AgentPolicy] = {}
    for path in sorted(_EXAMPLES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        policy = AgentPolicy.model_validate(data)
        policies[policy.agent.lower()] = policy
    return policies


def example_policies() -> list[AgentPolicy]:
    """The policies shipped as JSON files (the memory store, and the Postgres seed)."""
    return list(_load_all().values())


def list_policies() -> list[AgentPolicy]:
    """Return all known policies (runtime overrides take precedence by name)."""
    if get_settings().use_postgres:
        from app.persistence.identity import list_db_policies

        base = {p.agent.lower(): p for p in _cached("*", list_db_policies)}
    else:
        base = dict(_load_all())
    base.update(_overrides)
    return list(base.values())


def get_policy(agent: str) -> AgentPolicy | None:
    """Fetch a policy by agent name (case-insensitive); overrides win."""
    override = _overrides.get(agent.lower())
    if override is not None:
        return override
    if get_settings().use_postgres:
        from app.persistence.identity import get_db_policy

        return _cached(f"agent:{agent.lower()}", lambda: get_db_policy(agent))
    return _load_all().get(agent.lower())

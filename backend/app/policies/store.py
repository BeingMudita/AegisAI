"""Policy store — loads agent policies.

In memory mode policies come from the JSON files in ``app/policies/examples``.
With ``STORAGE_BACKEND=postgres`` they are read from the ``policies`` table
(seeded from those same files on first start). Keeping the lookup behind this
module means the API and engine don't change when the backing store does.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.policies.schemas import AgentPolicy

_EXAMPLES_DIR = Path(__file__).parent / "examples"


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
    """Return all known policies."""
    if get_settings().use_postgres:
        from app.persistence.identity import list_db_policies

        return list_db_policies()
    return example_policies()


def get_policy(agent: str) -> AgentPolicy | None:
    """Fetch a policy by agent name (case-insensitive)."""
    if get_settings().use_postgres:
        from app.persistence.identity import get_db_policy

        return get_db_policy(agent)
    return _load_all().get(agent.lower())

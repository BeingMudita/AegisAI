"""Policy store — loads agent policies.

Phase 2 loads policies from the JSON files in ``app/policies/examples``. This
is the interim source until policies are served from the ``policies`` table
(PostgreSQL is the eventual source of truth). Keeping the lookup behind this
module means the API and engine don't change when the backing store does.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

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


def list_policies() -> list[AgentPolicy]:
    """Return all known policies."""
    return list(_load_all().values())


def get_policy(agent: str) -> AgentPolicy | None:
    """Fetch a policy by agent name (case-insensitive)."""
    return _load_all().get(agent.lower())

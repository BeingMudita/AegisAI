"""Global policy configuration — loads ``default_policies.yaml``.

These are the system-wide rules (tool registry, RAG source rules) that sit
above the per-agent policies served by :mod:`app.policies.store`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from app.config import get_settings
from app.database.enums import ToolRiskLevel
from app.trust.scoring import TOOL_RISK_MIN_TRUST

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


class ToolPolicy(BaseModel):
    name: str
    description: str = ""
    risk_level: ToolRiskLevel = ToolRiskLevel.MEDIUM
    allowed: bool = True
    min_trust: float | None = Field(default=None, ge=0.0, le=1.0)
    rate_limit_per_min: int | None = Field(default=None, ge=1)
    data_category: str | None = None
    # High-impact actions: after every automatic check passes, wait for a human.
    requires_approval: bool = False

    @property
    def required_trust(self) -> float:
        """Explicit ``min_trust``, else the default for the tool's risk level."""
        if self.min_trust is not None:
            return self.min_trust
        return TOOL_RISK_MIN_TRUST[self.risk_level]


class RagPolicy(BaseModel):
    allow_untrusted_sources: bool = False
    min_source_trust: float = 0.3
    min_similarity: float = 0.15
    max_context_chunks: int = 5


class AuditPolicy(BaseModel):
    log_all_decisions: bool = True
    log_blocked_only: bool = False


class Defaults(BaseModel):
    default_action: str = "deny"


class BudgetLimits(BaseModel):
    """Daily limits for one principal (0 = unlimited). Reset at 00:00 UTC."""

    daily_turns: int = Field(default=500, ge=0)
    daily_tokens: int = Field(default=200_000, ge=0)
    daily_cost_usd: float = Field(default=0.0, ge=0)


class BudgetLimitsOverride(BaseModel):
    daily_turns: int | None = Field(default=None, ge=0)
    daily_tokens: int | None = Field(default=None, ge=0)
    daily_cost_usd: float | None = Field(default=None, ge=0)


class BudgetPricing(BaseModel):
    """USD per 1,000 tokens, used to turn token counts into cost."""

    prompt_per_1k: float = Field(default=0.0, ge=0)
    completion_per_1k: float = Field(default=0.0, ge=0)


class BudgetPolicy(BudgetLimits):
    """Per-principal consumption budgets (OWASP LLM10)."""

    max_output_tokens: int = Field(default=1024, ge=1)  # per LLM call
    pricing: BudgetPricing = Field(default_factory=BudgetPricing)
    roles: dict[str, BudgetLimitsOverride] = Field(default_factory=dict)
    principals: dict[str, BudgetLimitsOverride] = Field(default_factory=dict)

    def limits_for(self, principal: str, role: str | None) -> BudgetLimits:
        """The defaults, then the role's overrides, then the principal's."""
        values = BudgetLimits.model_validate(
            self.model_dump(include=set(BudgetLimits.model_fields))
        )
        for override in (self.roles.get(role or ""), self.principals.get(principal)):
            if override is not None:
                values = values.model_copy(update=override.model_dump(exclude_none=True))
        return values


class GlobalPolicyConfig(BaseModel):
    version: int = 1
    defaults: Defaults = Field(default_factory=Defaults)
    tools: list[ToolPolicy] = Field(default_factory=list)
    rag: RagPolicy = Field(default_factory=RagPolicy)
    audit: AuditPolicy = Field(default_factory=AuditPolicy)
    budgets: BudgetPolicy = Field(default_factory=BudgetPolicy)

    def tool(self, name: str) -> ToolPolicy | None:
        return next((t for t in self.tools if t.name == name), None)


def _resolve(path_str: str) -> Path:
    path = Path(path_str)
    if path.is_absolute() or path.exists():
        return path
    return _BACKEND_ROOT / path


@lru_cache
def get_global_config() -> GlobalPolicyConfig:
    """Load and cache the global policy file named by ``POLICY_CONFIG_PATH``."""
    path = _resolve(get_settings().policy_config_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return GlobalPolicyConfig.model_validate(data)


def register_tool_policy(tool_policy: ToolPolicy) -> ToolPolicy:
    """Upsert a tool policy into the cached global config, in place.

    The live :class:`~app.tools.gateway.ToolGateway` holds the very object returned
    by :func:`get_global_config`, so mutating its ``tools`` list here changes the
    gateway's behaviour with no restart. Used by the developer platform to apply
    ``aegis.yaml`` tool settings (``requires_approval``, ``min_trust``). Idempotent:
    re-registering the same tool replaces its entry.
    """
    config = get_global_config()
    for i, existing in enumerate(config.tools):
        if existing.name == tool_policy.name:
            config.tools[i] = tool_policy
            return tool_policy
    config.tools.append(tool_policy)
    return tool_policy

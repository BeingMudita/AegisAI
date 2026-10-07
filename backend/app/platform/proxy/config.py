"""The proxy config file — ``aegis-agent.yaml`` (Phase 9).

One declarative file describes how to put an existing agent behind AegisAI:
which agent, where its real LLM lives, which policy to enforce, and which
security controls to run::

    id: finance-agent
    mode: proxy

    upstream:
      type: openai-compatible
      url: http://localhost:8001

    policy:
      path: ./aegis.yaml

    security:
      input_firewall: true
      trust: true
      tool_gateway: true
      output_dlp: true

    audit:
      enabled: true

``aegis proxy --config aegis-agent.yaml`` loads this, applies the referenced
policy into the live engines, and starts the proxy.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

# Accept the human-friendly spelling as well as the adapter's registered name.
_UPSTREAM_ALIASES = {"openai-compatible": "openai", "openai": "openai", "mcp": "mcp"}


class UpstreamSection(BaseModel):
    type: str = "openai-compatible"
    # Where the agent's real LLM / tool server lives. Empty → use the built-in
    # AegisAI runtime as the upstream (self-contained; no external model needed).
    url: str | None = None

    @property
    def adapter(self) -> str:
        return _UPSTREAM_ALIASES.get(self.type.lower(), self.type.lower())


class PolicySection(BaseModel):
    path: str | None = None


class SecuritySection(BaseModel):
    input_firewall: bool = True
    trust: bool = True
    tool_gateway: bool = True
    output_dlp: bool = True


class AuditSection(BaseModel):
    enabled: bool = True


class AegisAgentConfig(BaseModel):
    """A validated ``aegis-agent.yaml`` document."""

    id: str
    mode: str = "proxy"
    upstream: UpstreamSection = Field(default_factory=UpstreamSection)
    policy: PolicySection = Field(default_factory=PolicySection)
    security: SecuritySection = Field(default_factory=SecuritySection)
    audit: AuditSection = Field(default_factory=AuditSection)

    # Resolved absolute path of the policy file (set by :func:`load_agent_config`).
    policy_path: Path | None = Field(default=None, exclude=True)

    def apply_policy(self) -> None:
        """Register the referenced ``aegis.yaml`` into the live engines, if any."""
        if self.policy_path is None:
            return
        from app.platform.policyfile import apply as apply_policy

        apply_policy(self.policy_path)


class ProxyConfigError(ValueError):
    """An ``aegis-agent.yaml`` file is missing or invalid."""


def load_agent_config(path: str | Path) -> AegisAgentConfig:
    """Read and validate an ``aegis-agent.yaml``; resolve the policy path."""
    p = Path(path)
    if not p.exists():
        raise ProxyConfigError(f"Config file not found: {p}")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ProxyConfigError(f"{p} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ProxyConfigError(f"{p} must be a YAML mapping, got {type(data).__name__}.")
    try:
        config = AegisAgentConfig.model_validate(data)
    except ValidationError as exc:
        raise ProxyConfigError(f"{p} is not a valid aegis-agent.yaml:\n{exc}") from exc
    if config.policy.path:
        policy_path = Path(config.policy.path)
        if not policy_path.is_absolute():
            policy_path = (p.parent / policy_path).resolve()
        config.policy_path = policy_path
    return config


SAMPLE_AGENT_YAML = """\
# aegis-agent.yaml — put an existing agent behind AegisAI without rewriting it.
id: {agent}
mode: proxy

upstream:
  # The agent's real, OpenAI-compatible LLM endpoint. Leave `url` empty to use
  # the built-in AegisAI runtime as the upstream (no external model required).
  type: openai-compatible
  url: ""

policy:
  # The policy-as-code file to enforce (see `aegis init`).
  path: ./aegis.yaml

security:
  input_firewall: true   # screen every user message for prompt injection
  trust: true            # gate tools on the agent's trust score
  tool_gateway: true     # deny-by-default authorization on every tool call
  output_dlp: true       # redact secrets / PII from responses

audit:
  enabled: true
"""


def sample_agent_yaml(agent: str = "finance-agent") -> str:
    """The starter ``aegis-agent.yaml`` written by ``aegis proxy --init``."""
    return SAMPLE_AGENT_YAML.format(agent=agent)

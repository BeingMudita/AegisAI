"""Policy-as-code — the ``aegis.yaml`` file.

A developer describes what one agent may do in a single declarative file, and
``apply`` wires it into the real engines: the agent policy goes to
:mod:`app.policies.store` (so the runtime, gateway and API all see it) and the
tool settings go to :mod:`app.policies.config` (so the live tool gateway honours
them). Nothing here enforces anything itself — it only configures the engines
that already do.

Example ``aegis.yaml``::

    agent:
      name: FinanceAgent
    permissions:
      tools: [search_documents, read_database, send_email]
    domains:
      allowed: [company.com]
    data:
      allow: [invoice, transaction]
      deny:  [customer_records, credentials]
    trust:
      minimum: 0.70
    approval:
      required_for: [send_email]
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from app.policies.config import ToolPolicy, get_global_config, register_tool_policy
from app.policies.schemas import AgentPolicy
from app.policies.store import register_policy
from app.tools.gateway import get_tool_gateway


class AgentSection(BaseModel):
    name: str


class PermissionsSection(BaseModel):
    tools: list[str] = Field(default_factory=list)


class DomainsSection(BaseModel):
    allowed: list[str] = Field(default_factory=list)


class DataSection(BaseModel):
    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


class TrustSection(BaseModel):
    minimum: float = Field(default=0.0, ge=0.0, le=1.0)


class ApprovalSection(BaseModel):
    required_for: list[str] = Field(default_factory=list)


class AegisFile(BaseModel):
    """A validated ``aegis.yaml`` document."""

    agent: AgentSection
    permissions: PermissionsSection = Field(default_factory=PermissionsSection)
    domains: DomainsSection = Field(default_factory=DomainsSection)
    data: DataSection = Field(default_factory=DataSection)
    trust: TrustSection = Field(default_factory=TrustSection)
    approval: ApprovalSection = Field(default_factory=ApprovalSection)

    # ------------------------------------------------------------- mapping
    def to_agent_policy(self) -> AgentPolicy:
        """The per-agent policy consumed by the policy engine and gateway.

        Deny-by-default already covers everything not listed, so only the
        allow-lists and the sensitive-data (``data.deny``) categories matter.
        """
        return AgentPolicy(
            agent=self.agent.name,
            allowed_tools=list(self.permissions.tools),
            blocked_tools=[],
            allowed_domains=list(self.domains.allowed),
            sensitive_data=list(self.data.deny),
        )

    def to_yaml(self) -> str:
        """Serialize back to ``aegis.yaml`` text (stable section order, omitting empties)."""
        data: dict = {
            "agent": {"name": self.agent.name},
            "permissions": {"tools": list(self.permissions.tools)},
        }
        if self.domains.allowed:
            data["domains"] = {"allowed": list(self.domains.allowed)}
        if self.data.allow or self.data.deny:
            section: dict = {}
            if self.data.allow:
                section["allow"] = list(self.data.allow)
            if self.data.deny:
                section["deny"] = list(self.data.deny)
            data["data"] = section
        if self.trust.minimum:
            data["trust"] = {"minimum": self.trust.minimum}
        if self.approval.required_for:
            data["approval"] = {"required_for": list(self.approval.required_for)}
        return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)

    def tool_overrides(self) -> list[ToolPolicy]:
        """Per-tool settings (approval, trust floor) built on the global registry.

        Each allowed tool's ``min_trust`` is raised to at least ``trust.minimum``;
        each tool in ``approval.required_for`` is marked ``requires_approval``.
        Existing registry metadata (risk level, rate limit, data category) is kept.
        """
        config = get_global_config()
        required_approval = {t for t in self.approval.required_for}
        names = set(self.permissions.tools) | required_approval
        overrides: list[ToolPolicy] = []
        for name in sorted(names):
            base = config.tool(name)
            tp = base.model_copy(deep=True) if base else ToolPolicy(name=name)
            floor = self.trust.minimum
            if floor > 0:
                tp.min_trust = max(tp.required_trust, floor)
            if name in required_approval:
                tp.requires_approval = True
            overrides.append(tp)
        return overrides

    def apply(self) -> ResolvedPosture:
        """Register this file into the live engines and return the resolved posture."""
        policy = self.to_agent_policy()
        register_policy(policy)
        overrides = self.tool_overrides()
        for tp in overrides:
            register_tool_policy(tp)
        return ResolvedPosture(
            agent=policy.agent,
            allowed_tools=policy.allowed_tools,
            allowed_domains=policy.allowed_domains,
            sensitive_data=policy.sensitive_data,
            trust_minimum=self.trust.minimum,
            approval_required=sorted(self.approval.required_for),
            warnings=self.lint(),
        )

    def lint(self) -> list[str]:
        """Non-fatal warnings: tools that the gateway does not know about."""
        known = {t.name for t in get_tool_gateway().describe()}
        warnings: list[str] = []
        for tool in self.permissions.tools:
            if tool not in known:
                warnings.append(f"Unknown tool '{tool}' — not in the tool registry.")
        for tool in self.approval.required_for:
            if tool not in self.permissions.tools:
                warnings.append(
                    f"'{tool}' is in approval.required_for but not in permissions.tools."
                )
        return warnings


class ResolvedPosture(BaseModel):
    """A human-readable summary of what an applied ``aegis.yaml`` means."""

    agent: str
    allowed_tools: list[str]
    allowed_domains: list[str]
    sensitive_data: list[str]
    trust_minimum: float
    approval_required: list[str]
    warnings: list[str] = Field(default_factory=list)


class PolicyFileError(ValueError):
    """An ``aegis.yaml`` file is missing or invalid."""


def load_aegis_file(path: str | Path) -> AegisFile:
    """Read and validate an ``aegis.yaml`` file, with clear error messages."""
    p = Path(path)
    if not p.exists():
        raise PolicyFileError(f"Policy file not found: {p}")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise PolicyFileError(f"{p} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise PolicyFileError(f"{p} must be a YAML mapping, got {type(data).__name__}.")
    try:
        return AegisFile.model_validate(data)
    except ValidationError as exc:
        raise PolicyFileError(f"{p} is not a valid aegis.yaml:\n{exc}") from exc


def apply(path_or_file: str | Path | AegisFile) -> ResolvedPosture:
    """Load (if needed) and apply an ``aegis.yaml`` into the live engines."""
    file = path_or_file if isinstance(path_or_file, AegisFile) else load_aegis_file(path_or_file)
    return file.apply()


def lint(path_or_file: str | Path | AegisFile) -> list[str]:
    """Return warnings for a policy file without applying it."""
    file = path_or_file if isinstance(path_or_file, AegisFile) else load_aegis_file(path_or_file)
    return file.lint()


SAMPLE_AEGIS_YAML = """\
# aegis.yaml — AegisAI policy-as-code.
# Describe what ONE agent may do; AegisAI enforces it (deny by default).
agent:
  name: {agent}

permissions:
  # Tools this agent may call. Anything not listed is denied.
  tools:
    - search_documents
    - read_database
    - generate_report
    - send_email

domains:
  # Allow-listed destinations for URL/email tool arguments.
  allowed:
    - company.com

data:
  # Informational: the data this agent legitimately handles.
  allow:
    - invoice
    - transaction
  # Treated as sensitive — redacted from outputs by DLP.
  deny:
    - customer_records
    - credentials

trust:
  # Minimum trust the agent must hold to use its tools (0–1).
  minimum: 0.70

approval:
  # High-impact tools that wait for a human, even after every check passes.
  required_for:
    - send_email
"""


def sample_yaml(agent: str = "FinanceAgent") -> str:
    """The starter ``aegis.yaml`` written by ``aegis init``."""
    return SAMPLE_AEGIS_YAML.format(agent=agent)

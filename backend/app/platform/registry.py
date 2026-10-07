"""The AegisAI agent registry — a connect → scan → protect onboarding flow.

A developer should not need to know about ``aegis.yaml``, ``aegis-agent.yaml``,
adapters, policies and the proxy to get started. They register an agent — its
framework, its tools, the data it touches — and AegisAI runs the whole front
half of the lifecycle for them::

    register → DISCOVER → AUDIT → GENERATE POLICY → RED-TEAM → CONFIGURE PROXY

then hands back a ready-to-run deployment configuration.

This is pure orchestration over the pieces that already exist: the policy-as-code
mapper, the scanner, the red-team gate and the proxy config.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.platform import scanner
from app.platform.gate import GateResult, run_gate
from app.platform.policyfile import (
    AegisFile,
    AgentSection,
    ApprovalSection,
    DataSection,
    DomainsSection,
    PermissionsSection,
    TrustSection,
)
from app.platform.proxy.config import UpstreamSection, sample_agent_yaml

_INTERNAL_DOMAIN = "company.com"


class AgentRegistration(BaseModel):
    """What a developer declares about their agent when they register it."""

    id: str
    framework: str = "openai-compatible"  # maps to an adapter (openai / mcp)
    tools: list[str] = Field(default_factory=list)
    data: list[str] = Field(default_factory=list)  # sensitive data categories handled
    domains: list[str] = Field(default_factory=list)  # external destinations it may reach
    status: str = "registered"  # registered | scanned | protected
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def adapter(self) -> str:
        return UpstreamSection(type=self.framework).adapter


class OnboardingResult(BaseModel):
    """Everything produced by scanning a registered agent."""

    agent: str
    score: int
    grade: str
    findings: list[dict] = Field(default_factory=list)
    aegis_yaml: str
    agent_yaml: str
    gate: GateResult | None = None


class RegistryError(ValueError):
    """The registry could not complete the request."""


class AgentRegistry:
    """An in-memory registry of onboarded agents (durable state lives in policies)."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentRegistration] = {}
        self._results: dict[str, OnboardingResult] = {}
        self._lock = threading.Lock()

    # --------------------------------------------------------------- register
    def register(self, registration: AgentRegistration) -> AgentRegistration:
        with self._lock:
            registration.status = "registered"
            self._agents[registration.id] = registration
            return registration

    def list(self) -> list[AgentRegistration]:
        with self._lock:
            return list(self._agents.values())

    def get(self, agent_id: str) -> AgentRegistration | None:
        with self._lock:
            return self._agents.get(agent_id)

    def result(self, agent_id: str) -> OnboardingResult | None:
        with self._lock:
            return self._results.get(agent_id)

    def clear(self) -> None:
        with self._lock:
            self._agents.clear()
            self._results.clear()

    # ----------------------------------------------------------------- scan
    def _to_aegis_file(self, reg: AgentRegistration) -> AegisFile:
        """Build a least-privilege starting policy from the declaration."""
        needs_domains = any(
            self._is_external(t) for t in reg.tools
        ) or bool(reg.domains)
        domains = reg.domains or ([_INTERNAL_DOMAIN] if needs_domains else [])
        approval = [t for t in reg.tools if self._is_high_impact(t)]
        return AegisFile(
            agent=AgentSection(name=reg.id),
            permissions=PermissionsSection(tools=list(reg.tools)),
            domains=DomainsSection(allowed=domains),
            data=DataSection(deny=list(reg.data)),
            trust=TrustSection(minimum=0.70),
            approval=ApprovalSection(required_for=approval),
        )

    @staticmethod
    def _tool_info(tool: str):
        from app.tools.gateway import get_tool_gateway

        return next((t for t in get_tool_gateway().describe() if t.name == tool), None)

    def _is_external(self, tool: str) -> bool:
        info = self._tool_info(tool)
        return bool(info and info.domain_checked_argument)

    def _is_high_impact(self, tool: str) -> bool:
        info = self._tool_info(tool)
        if info is None:
            return False
        return info.risk_level.value in {"HIGH", "CRITICAL"} or bool(info.domain_checked_argument)

    def onboard(self, agent_id: str, *, redteam: bool = True) -> OnboardingResult:
        """Run DISCOVER → AUDIT → GENERATE → RED-TEAM → CONFIGURE for one agent."""
        reg = self.get(agent_id)
        if reg is None:
            raise RegistryError(f"No agent '{agent_id}' is registered.")

        # 1. GENERATE a starting policy and APPLY it so the engines see the agent.
        self._to_aegis_file(reg).apply()

        # 2. AUDIT (discover from the applied policy + score it).
        profile = scanner.profile_known_agent(reg.id)
        report = scanner.score_report(profile)
        aegis_yaml = scanner.generate_policy(profile).to_yaml()

        # 3. Build the proxy config (CONFIGURE).
        agent_yaml = sample_agent_yaml(reg.id).replace(
            "type: openai-compatible", f"type: {reg.framework}"
        )

        # 4. RED-TEAM gate (optional — it is the slow step).
        gate = run_gate(reg.id, threshold=90, redteam=redteam) if redteam else None

        result = OnboardingResult(
            agent=reg.id,
            score=report.score,
            grade=report.grade,
            findings=[
                {"category": f.category, "severity": f.severity, "detail": f.detail}
                for f in report.findings
            ],
            aegis_yaml=aegis_yaml,
            agent_yaml=agent_yaml,
            gate=gate,
        )
        with self._lock:
            reg.status = "scanned"
            self._results[reg.id] = result
        return result

    # -------------------------------------------------------------- protect
    def protect(self, agent_id: str) -> dict:
        """Return the deployment configuration for a scanned agent."""
        reg = self.get(agent_id)
        if reg is None:
            raise RegistryError(f"No agent '{agent_id}' is registered.")
        result = self.result(agent_id)
        if result is None:
            result = self.onboard(agent_id, redteam=False)
        with self._lock:
            reg.status = "protected"
        return {
            "agent": reg.id,
            "adapter": reg.adapter,
            "aegis_yaml": result.aegis_yaml,
            "aegis_agent_yaml": result.agent_yaml,
            "run": "aegis proxy --config aegis-agent.yaml --port 9000",
            "endpoint": "/v1/chat/completions  (plus /v1/proxy/{tool,output,chat,mcp})",
        }


_registry = AgentRegistry()


def get_registry() -> AgentRegistry:
    """Return the process-wide agent registry."""
    return _registry

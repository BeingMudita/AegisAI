"""The tool gateway — the zero-trust checkpoint every tool call passes through.

Checks run cheapest-first; the first failure denies the call:

  1. registry    the tool exists and is not globally disabled
  2. policy      the agent's policy allows the tool (deny by default)
  3. domain      URL / email arguments point at an allow-listed domain
  4. firewall    the arguments carry no injection / abuse payload
  5. trust       the agent's trust score meets the tool's ``min_trust``
  6. rate_limit  the agent is within the tool's per-minute budget

After execution the output is scanned too — content coming *back* from a tool
is untrusted data (indirect injection) — and passed through DLP when the
agent's policy marks the tool's data category as sensitive.

Every outcome is audited and feeds the agent's trust score.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import urlparse

from app.config import get_settings
from app.database.enums import (
    SecurityEventType,
    SecuritySeverity,
    SubjectType,
    ToolRequestStatus,
    ToolRiskLevel,
)
from app.firewall.dlp import redact
from app.firewall.scanner import PromptFirewall, get_firewall
from app.firewall.schemas import ContentChannel, FirewallAction
from app.policies.config import GlobalPolicyConfig, ToolPolicy, get_global_config
from app.policies.engine import PolicyEngine
from app.policies.store import get_policy
from app.telemetry.store import get_audit_log
from app.tools.sandbox import IMPLEMENTATIONS, ToolContext, ToolImpl
from app.tools.schemas import CheckResult, ToolCallResult, ToolInfo
from app.trust.engine import TrustEngine, get_trust_engine
from app.trust.scoring import TrustSignal

_WITHHELD = "[Tool output withheld: the firewall detected an injection attempt in it.]"


class _Denied(Exception):
    """Internal: a checkpoint refused the call."""

    def __init__(
        self,
        checkpoint: str,
        reason: str,
        *,
        event: SecurityEventType | None = SecurityEventType.TOOL_DENIED,
        severity: SecuritySeverity = SecuritySeverity.MEDIUM,
        signal: TrustSignal | None = TrustSignal.TOOL_DENIED,
    ) -> None:
        super().__init__(reason)
        self.checkpoint = checkpoint
        self.reason = reason
        self.event = event
        self.severity = severity
        self.signal = signal


def _host(value: str, kind: str) -> str:
    if kind == "email":
        return value.rsplit("@", 1)[-1].strip().lower()
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return (parsed.hostname or "").lower()


class ToolGateway:
    def __init__(
        self,
        *,
        config: GlobalPolicyConfig,
        firewall: PromptFirewall,
        trust: TrustEngine,
        implementations: dict[str, ToolImpl] = IMPLEMENTATIONS,
    ) -> None:
        self.config = config
        self.firewall = firewall
        self.trust = trust
        self.implementations = implementations
        self._calls: dict[tuple[str, str], deque[float]] = {}
        self._log: deque[ToolCallResult] = deque(maxlen=1000)
        self._lock = threading.Lock()

    # -------------------------------------------------------------- catalog
    def describe(self) -> list[ToolInfo]:
        out = []
        for name, impl in self.implementations.items():
            tp = self.config.tool(name) or ToolPolicy(name=name, allowed=False)
            out.append(
                ToolInfo(
                    name=name,
                    description=tp.description,
                    risk_level=tp.risk_level,
                    enabled=tp.allowed,
                    required_trust=tp.required_trust,
                    rate_limit_per_min=tp.rate_limit_per_min,
                    data_category=tp.data_category,
                    parameters=impl.parameters,
                    domain_checked_argument=impl.domain_arg,
                )
            )
        return out

    def available_tools(self, agent: str) -> list[ToolInfo]:
        """Tools the agent's policy allows and that are globally enabled."""
        policy = get_policy(agent)
        if policy is None:
            return []
        engine = PolicyEngine(policy)
        return [t for t in self.describe() if t.enabled and engine.can_use_tool(t.name).allowed]

    def requests(self, *, agent: str | None = None, limit: int = 100) -> list[ToolCallResult]:
        with self._lock:
            items = list(self._log)
        items = [r for r in reversed(items) if agent is None or r.agent.lower() == agent.lower()]
        return items[:limit]

    def clear(self) -> None:
        with self._lock:
            self._calls.clear()
            self._log.clear()

    # ------------------------------------------------------------ execution
    def execute(
        self,
        agent: str,
        tool: str,
        arguments: dict | None = None,
        *,
        session_id: str | None = None,
    ) -> ToolCallResult:
        """Run ``tool`` for ``agent`` if — and only if — every checkpoint passes."""
        result = ToolCallResult(
            agent=agent, session_id=session_id, tool=tool, arguments=dict(arguments or {})
        )
        try:
            impl, tool_policy, policy_engine = self._authorize(result)
        except _Denied as denied:
            self._deny(result, denied)
            return self._finish(result)

        try:
            raw_output = impl.run(result.arguments, ToolContext(agent=agent, session_id=session_id))
        except Exception as exc:  # noqa: BLE001 — any tool failure is reported, not raised
            result.status = ToolRequestStatus.FAILED
            result.decision_reason = f"Tool error: {exc}"
            self.trust.observe(
                SubjectType.AGENT, agent, TrustSignal.TOOL_FAILURE, session_id=session_id
            )
            return self._finish(result)

        result.output = self._screen_output(result, impl, tool_policy, policy_engine, raw_output)
        result.status = ToolRequestStatus.EXECUTED
        result.decision_reason = (
            "Executed, but the output was withheld: the firewall found an injection in it."
            if result.output_action == FirewallAction.BLOCK
            else "All checkpoints passed."
        )
        self.trust.observe(
            SubjectType.AGENT,
            agent,
            TrustSignal.CLEAN_ACTION,
            rationale=f"Used {tool} within policy",
            session_id=session_id,
        )
        return self._finish(result)

    def _authorize(self, result: ToolCallResult) -> tuple[ToolImpl, ToolPolicy, PolicyEngine]:
        agent, tool, args = result.agent, result.tool, result.arguments
        checks = result.checks

        # 1. registry
        impl = self.implementations.get(tool)
        tool_policy = self.config.tool(tool)
        if impl is None or tool_policy is None:
            raise _Denied("registry", f"Unknown tool '{tool}' (deny by default).")
        if not tool_policy.allowed:
            raise _Denied(
                "registry",
                f"Tool '{tool}' is globally disabled ({tool_policy.risk_level.value} risk).",
                event=SecurityEventType.POLICY_VIOLATION,
                severity=_risk_severity(tool_policy.risk_level),
                signal=TrustSignal.POLICY_VIOLATION,
            )
        checks.append(
            CheckResult(
                checkpoint="registry", passed=True, detail=f"'{tool}' is registered and enabled."
            )
        )

        # 2. agent policy
        policy = get_policy(agent)
        if policy is None:
            raise _Denied(
                "policy",
                f"No policy exists for agent '{agent}'.",
                severity=SecuritySeverity.HIGH,
                signal=None,
            )
        engine = PolicyEngine(policy)
        decision = engine.can_use_tool(tool)
        get_audit_log().log_decision(
            "policy", allowed=decision.allowed, subject=tool, agent=agent, reason=decision.reason
        )
        if not decision.allowed:
            explicitly_blocked = tool in policy.blocked_tools
            raise _Denied(
                "policy",
                decision.reason,
                event=SecurityEventType.POLICY_VIOLATION,
                severity=SecuritySeverity.HIGH
                if explicitly_blocked
                else _risk_severity(tool_policy.risk_level),
                signal=TrustSignal.POLICY_VIOLATION,
            )
        checks.append(CheckResult(checkpoint="policy", passed=True, detail=decision.reason))

        # 3. domain allow-list
        if impl.domain_arg:
            value = str(args.get(impl.domain_arg, ""))
            host = _host(value, impl.domain_kind)
            domain_decision = engine.can_access_domain(host) if host else None
            allowed = bool(domain_decision and domain_decision.allowed)
            get_audit_log().log_decision(
                "policy", allowed=allowed, subject=host or value, agent=agent
            )
            if not allowed:
                raise _Denied(
                    "domain",
                    domain_decision.reason
                    if domain_decision
                    else f"Argument '{impl.domain_arg}' has no valid domain.",
                    event=SecurityEventType.POLICY_VIOLATION,
                    severity=SecuritySeverity.HIGH,
                    signal=TrustSignal.POLICY_VIOLATION,
                )
            checks.append(
                CheckResult(checkpoint="domain", passed=True, detail=domain_decision.reason)
            )

        # 4. firewall over the arguments
        verdict = self.firewall.inspect(
            json.dumps(args, ensure_ascii=False),
            ContentChannel.TOOL_ARGUMENTS,
            agent=agent,
            session_id=result.session_id,
            context=f"arguments to {tool}",
        )
        if verdict.action == FirewallAction.BLOCK:
            raise _Denied("firewall", verdict.reason, event=None, signal=TrustSignal.FIREWALL_BLOCK)
        if verdict.action == FirewallAction.FLAG:
            self.trust.observe(
                SubjectType.AGENT, agent, TrustSignal.FIREWALL_FLAG, session_id=result.session_id
            )
        checks.append(CheckResult(checkpoint="firewall", passed=True, detail=verdict.reason))

        # 5. trust
        trust = self.trust.evaluate(
            SubjectType.AGENT, agent, required=tool_policy.required_trust, action=f"use {tool}"
        )
        if not trust.allowed:
            raise _Denied("trust", trust.reason)
        checks.append(CheckResult(checkpoint="trust", passed=True, detail=trust.reason))

        # 6. rate limit
        if tool_policy.rate_limit_per_min:
            if not self._take_rate_slot(agent, tool, tool_policy.rate_limit_per_min):
                raise _Denied(
                    "rate_limit",
                    f"Rate limit of {tool_policy.rate_limit_per_min}/min for '{tool}' exceeded.",
                    event=SecurityEventType.ANOMALY,
                )
            checks.append(
                CheckResult(checkpoint="rate_limit", passed=True, detail="Within rate limit.")
            )

        return impl, tool_policy, engine

    def _screen_output(
        self,
        result: ToolCallResult,
        impl: ToolImpl,
        tool_policy: ToolPolicy,
        policy_engine: PolicyEngine,
        output: str,
    ) -> str:
        verdict = self.firewall.inspect(
            output,
            ContentChannel.TOOL_OUTPUT,
            agent=result.agent,
            session_id=result.session_id,
            context=f"output of {result.tool}",
        )
        result.output_action = verdict.action
        if verdict.action == FirewallAction.BLOCK:
            source = (
                _host(str(result.arguments.get(impl.domain_arg, "")), impl.domain_kind)
                if impl.domain_arg
                else ""
            )
            self.trust.observe(
                SubjectType.SOURCE,
                source or result.tool,
                TrustSignal.INJECTED_CONTENT,
                rationale=f"Injection in output of {result.tool}",
                session_id=result.session_id,
            )
            result.checks.append(
                CheckResult(checkpoint="output", passed=False, detail=verdict.reason)
            )
            return _WITHHELD
        if verdict.action == FirewallAction.FLAG:
            output = self.firewall.sanitize(output, verdict)
        result.checks.append(CheckResult(checkpoint="output", passed=True, detail=verdict.reason))

        sensitive = bool(tool_policy.data_category) and policy_engine.is_sensitive(
            tool_policy.data_category
        )
        dlp = redact(output, pii=sensitive)
        if dlp.redacted:
            result.redactions = dict(dlp.redactions)
            result.checks.append(
                CheckResult(
                    checkpoint="dlp",
                    passed=True,
                    detail="Redacted "
                    + ", ".join(f"{n} {k}" for k, n in sorted(dlp.redactions.items())),
                )
            )
        return dlp.text

    # -------------------------------------------------------------- helpers
    def _take_rate_slot(self, agent: str, tool: str, limit: int) -> bool:
        now = time.monotonic()
        with self._lock:
            window = self._calls.setdefault((agent.lower(), tool), deque())
            while window and now - window[0] > 60:
                window.popleft()
            if len(window) >= limit:
                return False
            window.append(now)
            return True

    def _deny(self, result: ToolCallResult, denied: _Denied) -> None:
        result.status = ToolRequestStatus.DENIED
        result.decision_reason = denied.reason
        result.checks.append(
            CheckResult(checkpoint=denied.checkpoint, passed=False, detail=denied.reason)
        )
        if denied.event is not None:
            get_audit_log().record_event(
                event_type=denied.event,
                severity=denied.severity,
                source="tools",
                agent=result.agent,
                session_id=result.session_id,
                description=f"Denied {result.tool} at {denied.checkpoint}: {denied.reason}",
                details={
                    "tool": result.tool,
                    "checkpoint": denied.checkpoint,
                    "arguments": result.arguments,
                },
            )
        if denied.signal is not None:
            self.trust.observe(
                SubjectType.AGENT,
                result.agent,
                denied.signal,
                rationale=f"{result.tool} denied at {denied.checkpoint}",
                session_id=result.session_id,
            )

    def _finish(self, result: ToolCallResult) -> ToolCallResult:
        result.decided_at = datetime.now(timezone.utc)
        get_audit_log().log_decision(
            "tools",
            allowed=result.executed,
            subject=result.tool,
            agent=result.agent,
            reason=result.decision_reason,
        )
        self._store_request(result)
        return result

    def _store_request(self, result: ToolCallResult) -> None:
        with self._lock:
            self._log.append(result)


def _risk_severity(risk: ToolRiskLevel) -> SecuritySeverity:
    return {
        ToolRiskLevel.LOW: SecuritySeverity.LOW,
        ToolRiskLevel.MEDIUM: SecuritySeverity.MEDIUM,
        ToolRiskLevel.HIGH: SecuritySeverity.HIGH,
        ToolRiskLevel.CRITICAL: SecuritySeverity.CRITICAL,
    }[risk]


@lru_cache
def get_tool_gateway() -> ToolGateway:
    """Return the process-wide tool gateway (shared log and limits in Postgres mode)."""
    kwargs = {
        "config": get_global_config(),
        "firewall": get_firewall(),
        "trust": get_trust_engine(),
    }
    if get_settings().use_postgres:
        from app.persistence.tools import PostgresToolGateway

        return PostgresToolGateway(**kwargs)
    return ToolGateway(**kwargs)

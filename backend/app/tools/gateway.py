"""The tool gateway — the zero-trust checkpoint every tool call passes through.

Checks run cheapest-first; the first failure denies the call:

  1. registry    the tool exists and is not globally disabled
  2. policy      the agent's policy allows the tool (deny by default)
  3. domain      URL / email arguments name exactly one destination, on an
                 allow-listed domain (https only; one plain address per email)
  4. firewall    the arguments carry no injection / abuse payload
  5. trust       the agent's trust score meets the tool's ``min_trust``
  6. rate_limit  the agent is within the tool's per-minute budget

Free-text arguments of tools that send data out (an email body, an upload) pass
through DLP before the call is queued or run: secrets always, personal data when
the agent handles sensitive data.

After execution the output is scanned too — content coming *back* from a tool
is untrusted data (indirect injection) — and passed through DLP when the
agent's policy marks the tool's data category as sensitive.

Every outcome is audited and feeds the agent's trust score — its score with the
principal who requested the call, when there is one (see :mod:`app.trust.engine`).

Tools marked ``requires_approval`` stop after the checkpoints pass: the request
is queued for a human. On approval every checkpoint is re-run (the agent's trust,
its policy or the domain list may have changed meanwhile) before the tool runs;
claiming a request is atomic, so it can never execute twice.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any
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
from app.tools.sandbox import IMPLEMENTATIONS, OUTBOX, ToolContext, ToolImpl
from app.tools.schemas import CheckResult, ToolCallResult, ToolInfo
from app.trust.engine import TrustEngine, get_trust_engine
from app.trust.scoring import TrustSignal

_WITHHELD = "[Tool output withheld: the firewall detected an injection attempt in it.]"


class ApprovalError(Exception):
    """The request can't be approved or rejected (unknown, or already decided)."""

    def __init__(self, message: str, *, not_found: bool = False) -> None:
        super().__init__(message)
        self.not_found = not_found


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


# One plain address: no display name, no list, no second "@" — the whole value must match.
_EMAIL_ADDRESS = re.compile(r"[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})")


def _host(value: str, kind: str) -> str | None:
    """The domain a URL / email argument points at — or None unless it names exactly
    one destination unambiguously.

    Ambiguous values are refused rather than parsed leniently, because a lenient
    parser and the real mail server or HTTP client could disagree on the destination:
    ``"x@evil.io, y@company.com"`` must not count as ``company.com``, nor
    ``https://evil.io\\@company.com`` (browsers read the backslash as a path).
    """
    value = value.strip()
    if kind == "email":
        match = _EMAIL_ADDRESS.fullmatch(value)
        return match.group(1).lower() if match else None
    if not value or any(ch.isspace() or ch == "\\" or not ch.isprintable() for ch in value):
        return None
    parsed = urlparse(value if "://" in value else f"https://{value}")
    try:
        if parsed.scheme.lower() != "https" or parsed.username or parsed.password:
            return None
        host = parsed.hostname
    except ValueError:
        return None
    return host.lower() if host else None


class ToolGateway:
    def __init__(
        self,
        *,
        config: GlobalPolicyConfig,
        firewall: PromptFirewall,
        trust: TrustEngine,
        implementations: dict[str, ToolImpl] = IMPLEMENTATIONS,
        knowledge_base: object | None = None,
        outbox: list[dict[str, str]] | None = None,
    ) -> None:
        self.config = config
        self.firewall = firewall
        self.trust = trust
        self.implementations = implementations
        # What the sandboxed tools read and write. None = the process-wide knowledge
        # base and outbox; an isolated runtime (red-team runs) passes its own.
        self.knowledge_base = knowledge_base
        self.outbox = OUTBOX if outbox is None else outbox
        self._calls: dict[tuple[str, str], deque[float]] = {}
        self._log: deque[ToolCallResult] = deque(maxlen=1000)
        self._by_id: dict[str, ToolCallResult] = {}
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
                    requires_approval=tp.requires_approval,
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
            self._by_id.clear()

    # ------------------------------------------------------------ execution
    def execute(
        self,
        agent: str,
        tool: str,
        arguments: dict | None = None,
        *,
        session_id: str | None = None,
        principal: str | None = None,
    ) -> ToolCallResult:
        """Run ``tool`` for ``agent`` if — and only if — every checkpoint passes.

        ``principal`` is who the agent is acting for (the session's user); trust
        decisions and signals use the agent's score with them.
        """
        result = ToolCallResult(
            agent=agent,
            session_id=session_id,
            requested_by=principal,
            tool=tool,
            arguments=dict(arguments or {}),
        )
        try:
            impl, tool_policy, policy_engine = self._authorize(result)
        except _Denied as denied:
            self._deny(result, denied)
            return self._finish(result)
        self._redact_egress(result, impl, policy_engine)

        if tool_policy.requires_approval:
            return self._queue_for_approval(result, tool_policy)
        return self._run(result, impl, tool_policy, policy_engine)

    def authorize(
        self,
        agent: str,
        tool: str,
        arguments: dict | None = None,
        *,
        session_id: str | None = None,
    ) -> ToolCallResult:
        """Run the checkpoint ladder for a tool call and report the decision
        **without executing the tool** — a pre-flight / dry run.

        It is the same authorization the real gateway performs (registry → policy →
        domain → firewall → trust → rate limit), so denials are recorded and audited
        exactly as :meth:`execute` would. The only difference is that the tool
        implementation never runs: an allowed call reports ``APPROVED`` (authorized,
        would run), a high-impact call reports ``PENDING`` (would be queued for a
        human), and a refused call reports ``DENIED`` with the failing checkpoint.

        Powers ``POST /v1/secure/tool`` and the (future) MCP security proxy.
        """
        result = ToolCallResult(
            agent=agent, session_id=session_id, tool=tool, arguments=dict(arguments or {})
        )
        try:
            _impl, tool_policy, _engine = self._authorize(result)
        except _Denied as denied:
            self._deny(result, denied)
            result.decided_at = datetime.now(timezone.utc)
            return result
        if tool_policy.requires_approval:
            result.status = ToolRequestStatus.PENDING
            result.decision_reason = (
                f"Authorized, but '{tool}' is a {tool_policy.risk_level.value.lower()}-risk "
                "action that would be queued for human approval before running."
            )
            result.checks.append(
                CheckResult(
                    checkpoint="approval",
                    passed=False,
                    detail="Requires a human decision before it can run.",
                )
            )
        else:
            result.status = ToolRequestStatus.APPROVED
            result.decision_reason = "All checkpoints passed (dry run — the tool was not executed)."
        result.decided_at = datetime.now(timezone.utc)
        return result

    def _run(
        self,
        result: ToolCallResult,
        impl: ToolImpl,
        tool_policy: ToolPolicy,
        policy_engine: PolicyEngine,
    ) -> ToolCallResult:
        agent, session_id = result.agent, result.session_id
        context = ToolContext(
            agent=agent,
            session_id=session_id,
            knowledge_base=self.knowledge_base,
            outbox=self.outbox,
        )
        try:
            raw_output = impl.run(result.arguments, context)
        except Exception as exc:  # noqa: BLE001 — any tool failure is reported, not raised
            result.status = ToolRequestStatus.FAILED
            result.decision_reason = f"Tool error: {exc}"
            self.trust.observe_agent(
                agent, result.requested_by, TrustSignal.TOOL_FAILURE, session_id=session_id
            )
            return self._finish(result)

        result.output = self._screen_output(result, impl, tool_policy, policy_engine, raw_output)
        result.status = ToolRequestStatus.EXECUTED
        if result.output_action == FirewallAction.BLOCK:
            result.decision_reason = (
                "Executed, but the output was withheld: the firewall found an injection in it."
            )
        elif result.reviewed_by:
            result.decision_reason = (
                f"Approved by {result.reviewed_by}; every checkpoint re-verified and passed."
            )
        else:
            result.decision_reason = "All checkpoints passed."
        self.trust.observe_agent(
            agent,
            result.requested_by,
            TrustSignal.CLEAN_ACTION,
            rationale=f"Used {result.tool} within policy",
            session_id=session_id,
        )
        return self._finish(result)

    # ------------------------------------------------------- human approval
    def _queue_for_approval(
        self, result: ToolCallResult, tool_policy: ToolPolicy
    ) -> ToolCallResult:
        ttl = get_settings().approval_ttl_minutes
        result.status = ToolRequestStatus.PENDING
        result.expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl)
        result.decision_reason = (
            f"Waiting for human approval: '{result.tool}' is a "
            f"{tool_policy.risk_level.value.lower()}-risk action."
        )
        result.checks.append(
            CheckResult(
                checkpoint="approval",
                passed=False,
                detail=f"Queued for an administrator's decision (expires in {ttl} min).",
            )
        )
        self._save_request(result)
        return result

    def approval_queue(
        self, *, limit: int = 50
    ) -> tuple[list[ToolCallResult], list[ToolCallResult]]:
        """(pending, recently decided) — expired requests are closed first."""
        self._expire_pending()
        return self._pending_requests(), self._decided_approvals(limit)

    def pending_count(self) -> int:
        """How many requests wait for a decision (expired ones are closed first)."""
        self._expire_pending()
        return self._count_pending()

    def approve(self, request_id: str, reviewer: str, note: str = "") -> ToolCallResult:
        """Approve a queued request: re-verify every checkpoint, then run the tool."""
        self._expire_pending()
        result = self._claim(request_id, reviewer, note)
        result.checks = [c for c in result.checks if c.checkpoint != "approval"]
        result.checks.append(
            CheckResult(
                checkpoint="approval",
                passed=True,
                detail=f"Approved by {reviewer}" + (f": {note}" if note else "."),
            )
        )
        recheck = result.model_copy(update={"checks": []})
        try:
            impl, tool_policy, policy_engine = self._authorize(recheck)
        except _Denied as denied:
            result.checks.extend(recheck.checks)
            denied.reason = f"Approved, but the re-check at approval time failed: {denied.reason}"
            self._deny(result, denied)
            return self._finish(result)
        result.checks.append(
            CheckResult(
                checkpoint="recheck",
                passed=True,
                detail="Policy, domain, firewall, trust and rate limit re-verified at approval.",
            )
        )
        return self._run(result, impl, tool_policy, policy_engine)

    def reject(self, request_id: str, reviewer: str, note: str = "") -> ToolCallResult:
        """Reject a queued request; the agent takes a small trust penalty."""
        self._expire_pending()
        result = self._claim(request_id, reviewer, note)
        reason = f"Rejected by {reviewer}" + (f": {note}" if note else ".")
        result.checks = [c for c in result.checks if c.checkpoint != "approval"]
        self._deny(
            result,
            _Denied(
                "approval",
                reason,
                event=SecurityEventType.TOOL_DENIED,
                severity=SecuritySeverity.MEDIUM,
                signal=TrustSignal.TOOL_DENIED,
            ),
        )
        return self._finish(result)

    def _expire_pending(self) -> None:
        for pending in self._expired_requests(datetime.now(timezone.utc)):
            try:
                result = self._claim(pending.id, "system", "expired")
            except ApprovalError:
                continue  # decided concurrently
            result.reviewed_by = None
            result.review_note = None
            result.checks = [c for c in result.checks if c.checkpoint != "approval"]
            result.checks.append(
                CheckResult(checkpoint="approval", passed=False, detail="Expired.")
            )
            result.status = ToolRequestStatus.DENIED
            result.decision_reason = "No decision before the approval request expired."
            self._finish(result)

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
                expected = (
                    "a single plain email address"
                    if impl.domain_kind == "email"
                    else "one https URL"
                )
                raise _Denied(
                    "domain",
                    domain_decision.reason
                    if domain_decision
                    else f"Argument '{impl.domain_arg}' must be {expected} on an allowed domain.",
                    event=SecurityEventType.POLICY_VIOLATION,
                    severity=SecuritySeverity.HIGH,
                    signal=TrustSignal.POLICY_VIOLATION,
                )
            assert domain_decision is not None  # allowed implies a decision was made
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
            self.trust.observe_agent(
                agent, result.requested_by, TrustSignal.FIREWALL_FLAG, session_id=result.session_id
            )
        checks.append(CheckResult(checkpoint="firewall", passed=True, detail=verdict.reason))

        # 5. trust
        trust = self.trust.evaluate_agent(
            agent, result.requested_by, required=tool_policy.required_trust, action=f"use {tool}"
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

        category = tool_policy.data_category
        sensitive = category is not None and policy_engine.is_sensitive(category)
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

    def _redact_egress(
        self, result: ToolCallResult, impl: ToolImpl, policy_engine: PolicyEngine
    ) -> None:
        """DLP over the free text a tool sends out — before it is queued or run, so
        neither the recipient nor the stored request (and its reviewer) sees secrets."""
        counts: Counter[str] = Counter()
        pii = bool(policy_engine.policy.sensitive_data)
        for name in impl.egress_args:
            value = result.arguments.get(name)
            if not isinstance(value, str):
                continue
            dlp = redact(value, pii=pii)
            if dlp.redacted:
                result.arguments[name] = dlp.text
                counts.update(dlp.redactions)
        if counts:
            result.redactions = dict(counts)
            result.checks.append(
                CheckResult(
                    checkpoint="dlp",
                    passed=True,
                    detail="Redacted outgoing "
                    + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())),
                )
            )

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
            self.trust.observe_agent(
                result.agent,
                result.requested_by,
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
        self._save_request(result)
        return result

    # ------------------------------------------------ storage (memory)
    def _save_request(self, result: ToolCallResult) -> None:
        """Insert or update a request record."""
        with self._lock:
            if result.id in self._by_id:
                for i, existing in enumerate(self._log):
                    if existing.id == result.id:
                        self._log[i] = result
                        break
            else:
                if len(self._log) == self._log.maxlen:
                    self._by_id.pop(self._log[0].id, None)
                self._log.append(result)
            self._by_id[result.id] = result

    def _pending_requests(self) -> list[ToolCallResult]:
        with self._lock:
            return [r.model_copy(deep=True) for r in reversed(self._log) if r.pending]

    def _count_pending(self) -> int:
        with self._lock:
            return sum(r.pending for r in self._log)

    def _expired_requests(self, now: datetime) -> list[ToolCallResult]:
        with self._lock:
            return [
                r.model_copy(deep=True)
                for r in self._log
                if r.pending and r.expires_at and r.expires_at <= now
            ]

    def _decided_approvals(self, limit: int) -> list[ToolCallResult]:
        """Requests that went through the approval queue and have been closed."""
        with self._lock:
            decided = [r for r in reversed(self._log) if r.expires_at and not r.pending]
        return [r.model_copy(deep=True) for r in decided[:limit]]

    def _claim(self, request_id: str, reviewer: str, note: str) -> ToolCallResult:
        """Atomically move a PENDING request to APPROVED (under review) and return it."""
        with self._lock:
            result = self._by_id.get(request_id)
            if result is None:
                raise ApprovalError("Approval request not found.", not_found=True)
            if not result.pending:
                raise ApprovalError(f"Request is already {result.status.value.lower()}.")
            result.status = ToolRequestStatus.APPROVED
            result.reviewed_by = reviewer
            result.review_note = note or None
            result.reviewed_at = datetime.now(timezone.utc)
            return result.model_copy(deep=True)


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
    kwargs: dict[str, Any] = {
        "config": get_global_config(),
        "firewall": get_firewall(),
        "trust": get_trust_engine(),
    }
    if get_settings().use_postgres:
        from app.persistence.tools import PostgresToolGateway

        return PostgresToolGateway(**kwargs)
    return ToolGateway(**kwargs)

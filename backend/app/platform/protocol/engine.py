"""The security engine — the single place an :class:`AegisEvent` is judged.

The engine owns no security logic of its own. It is a *router*: it translates a
framework-neutral event into a call on the real engines the dashboard already
uses — the prompt-injection firewall, the deny-by-default tool gateway, the
trust engine and DLP — and translates their verdicts back into one
:class:`AegisDecision`.

    AegisEvent ──▶ SecurityEngine ──▶ { firewall | gateway | trust | DLP } ──▶ AegisDecision

Keeping this the only translation point is what lets every adapter stay thin:
an adapter's job ends at producing an :class:`AegisEvent`.
"""

from __future__ import annotations

from functools import lru_cache

from app.database.enums import SubjectType, ToolRequestStatus
from app.firewall.dlp import redact
from app.firewall.scanner import PromptFirewall, get_firewall
from app.firewall.schemas import ContentChannel, FirewallAction
from app.platform.protocol.events import AegisEvent, AegisEventType
from app.platform.protocol.schemas import AegisDecision, CheckOutcome, Decision
from app.tools.gateway import ToolGateway, get_tool_gateway
from app.trust.engine import TrustEngine, get_trust_engine

# The checkpoint a tool call failed at → a stable, machine-readable reason code.
_TOOL_REASON_CODE = {
    "registry": "unknown_tool",
    "policy": "policy_denied",
    "domain": "untrusted_external_destination",
    "firewall": "injection_detected",
    "trust": "trust_requirement_failed",
    "rate_limit": "rate_limited",
    "approval": "awaiting_human_approval",
}


class SecurityEngine:
    """Evaluate :class:`AegisEvent`s against the live AegisAI security stack."""

    def __init__(
        self,
        *,
        firewall: PromptFirewall | None = None,
        gateway: ToolGateway | None = None,
        trust: TrustEngine | None = None,
    ) -> None:
        self.firewall = firewall or get_firewall()
        self.gateway = gateway or get_tool_gateway()
        self.trust = trust or get_trust_engine()

    @property
    def intel(self):
        from app.platform.threatintel import get_threat_intel

        return get_threat_intel()

    # ------------------------------------------------------------- dispatch
    def evaluate(self, event: AegisEvent) -> AegisDecision:
        """Judge one event and return a single decision."""
        handler = {
            AegisEventType.INPUT: self._input,
            AegisEventType.RETRIEVAL: self._retrieval,
            AegisEventType.TOOL_PROPOSAL: self._tool_proposal,
            AegisEventType.TOOL_RESULT: self._tool_result,
            AegisEventType.OUTPUT: self._output,
        }[event.event_type]
        return handler(event)

    # ------------------------------------------------------------- helpers
    def _trust_score(self, agent: str) -> float:
        return self.trust.score(SubjectType.AGENT, agent)

    def _base(self, event: AegisEvent, **kw) -> dict:
        return {
            "event_type": event.event_type,
            "agent": event.agent,
            "session_id": event.session_id,
            "trust_score": round(self._trust_score(event.agent), 4),
            **kw,
        }

    # --------------------------------------------------------------- INPUT
    def _input(self, event: AegisEvent) -> AegisDecision:
        text = event.text or ""
        match = self.intel.match(text)  # before recording, so it can't match itself
        verdict = self.firewall.inspect(
            text,
            ContentChannel.USER_INPUT,
            agent=event.agent,
            session_id=event.session_id,
            context="proxy input",
        )
        self.intel.record_verdict(verdict, text, agent=event.agent)
        if verdict.action == FirewallAction.BLOCK:
            return AegisDecision(
                decision=Decision.BLOCK,
                reason=verdict.reason,
                reason_code="prompt_injection",
                checks={"firewall": CheckOutcome.FAIL, "threat_intel": _intel_check(match)},
                categories=verdict.categories,
                **self._base(event),
            )
        sanitized = (
            self.firewall.sanitize(text, verdict) if verdict.action == FirewallAction.FLAG else text
        )
        decision = Decision.FLAG if verdict.action == FirewallAction.FLAG else Decision.ALLOW
        reason = verdict.reason
        reason_code = "suspicious_input" if verdict.action == FirewallAction.FLAG else "ok"
        # Preemptive detection: a known HIGH attack pattern escalates a clean verdict.
        if match is not None and match.severity == "HIGH":
            decision = Decision.BLOCK if decision == Decision.FLAG else Decision.FLAG
            reason, reason_code = match.reason, "known_attack_pattern"
        return AegisDecision(
            decision=decision,
            reason=reason,
            reason_code=reason_code,
            checks={"firewall": CheckOutcome.PASS, "threat_intel": _intel_check(match)},
            sanitized_text=sanitized,
            categories=verdict.categories,
            **self._base(event),
        )

    # ----------------------------------------------------------- RETRIEVAL
    def _retrieval(self, event: AegisEvent) -> AegisDecision:
        quarantined: list[int] = []
        flagged = False
        preempted = False
        categories: set[str] = set()
        kept: list[str] = []
        for i, doc in enumerate(event.documents):
            match = self.intel.match(doc.content)
            verdict = self.firewall.inspect(
                doc.content,
                ContentChannel.RETRIEVED,
                agent=event.agent,
                session_id=event.session_id,
                context=f"retrieved from {doc.source}",
            )
            self.intel.record_verdict(verdict, doc.content, agent=event.agent)
            categories.update(verdict.categories)
            known_attack = match is not None and match.severity == "HIGH"
            if verdict.action == FirewallAction.BLOCK:
                quarantined.append(i)
            elif known_attack:  # preemptive: quarantine a known attack the firewall let pass
                quarantined.append(i)
                preempted = True
                categories.add("KNOWN_THREAT")
            elif verdict.action == FirewallAction.FLAG:
                flagged = True
                kept.append(self.firewall.sanitize(doc.content, verdict))
            else:
                kept.append(doc.content)
        if quarantined:
            reason = (
                f"Quarantined {len(quarantined)} of {len(event.documents)} "
                "document(s) with injected instructions."
            )
            code = "known_attack_pattern" if preempted else "untrusted_content_quarantined"
            decision = Decision.FLAG
        elif flagged:
            reason = "Retrieved content was sanitized before use."
            code = "retrieved_content_sanitized"
            decision = Decision.FLAG
        else:
            reason = "Retrieved content is clean."
            code = "ok"
            decision = Decision.ALLOW
        return AegisDecision(
            decision=decision,
            reason=reason,
            reason_code=code,
            checks={"firewall": CheckOutcome.PASS if not quarantined else CheckOutcome.FAIL},
            sanitized_text="\n\n".join(kept) if kept else None,
            categories=sorted(categories),
            quarantined=quarantined,
            **self._base(event),
        )

    # ------------------------------------------------------- TOOL_PROPOSAL
    def _tool_proposal(self, event: AegisEvent) -> AegisDecision:
        tool = event.tool
        if tool is None:
            return AegisDecision(
                decision=Decision.BLOCK,
                reason="A TOOL_PROPOSAL event must carry a tool.",
                reason_code="malformed_event",
                **self._base(event),
            )
        result = self.gateway.authorize(
            event.agent, tool.name, tool.arguments, session_id=event.session_id
        )
        checks = {
            c.checkpoint: CheckOutcome.PASS if c.passed else CheckOutcome.FAIL
            for c in result.checks
        }
        failed = next((c.checkpoint for c in result.checks if not c.passed), None)

        if result.status == ToolRequestStatus.DENIED:
            decision = Decision.BLOCK
        elif result.status == ToolRequestStatus.PENDING:
            decision = Decision.APPROVAL
        else:
            decision = Decision.ALLOW
        code = _TOOL_REASON_CODE.get(failed or "", "ok") if decision != Decision.ALLOW else "ok"
        # Learn an exfiltration signature when a sensitive external send is refused.
        if decision == Decision.BLOCK and failed == "domain":
            self.intel.record_text(
                f"{tool.name} -> {tool.arguments}",
                ["DATA_EXFILTRATION"],
                severity="HIGH",
                agent=event.agent,
                tool=tool.name,
                destination="external",
            )
        return AegisDecision(
            decision=decision,
            reason=result.decision_reason,
            reason_code=code,
            checks=checks,
            **self._base(event),
        )

    # --------------------------------------------------------- TOOL_RESULT
    def _tool_result(self, event: AegisEvent) -> AegisDecision:
        return self._screen_data(
            event, channel=ContentChannel.TOOL_OUTPUT, context="tool output"
        )

    # -------------------------------------------------------------- OUTPUT
    def _output(self, event: AegisEvent) -> AegisDecision:
        return self._screen_data(event, channel=ContentChannel.TOOL_OUTPUT, context="agent output")

    def _screen_data(
        self, event: AegisEvent, *, channel: ContentChannel, context: str
    ) -> AegisDecision:
        """Shared path for TOOL_RESULT / OUTPUT: injection scan, then DLP."""
        text = event.text or ""
        match = self.intel.match(text)
        verdict = self.firewall.inspect(
            text, channel, agent=event.agent, session_id=event.session_id, context=context
        )
        self.intel.record_verdict(verdict, text, agent=event.agent)
        if verdict.action == FirewallAction.BLOCK:
            return AegisDecision(
                decision=Decision.BLOCK,
                reason=verdict.reason,
                reason_code="injection_in_data",
                checks={"firewall": CheckOutcome.FAIL, "dlp": CheckOutcome.SKIP},
                categories=verdict.categories,
                **self._base(event),
            )
        known = match is not None and match.severity == "HIGH"
        if known and verdict.action == FirewallAction.ALLOW:
            return AegisDecision(
                decision=Decision.BLOCK,
                reason=match.reason,
                reason_code="known_attack_pattern",
                checks={"firewall": CheckOutcome.PASS, "threat_intel": CheckOutcome.FAIL},
                categories=[*verdict.categories, "KNOWN_THREAT"],
                **self._base(event),
            )
        cleaned = (
            self.firewall.sanitize(text, verdict) if verdict.action == FirewallAction.FLAG else text
        )
        dlp = redact(cleaned, pii=True)
        modified = verdict.action == FirewallAction.FLAG or dlp.redacted
        return AegisDecision(
            decision=Decision.FLAG if modified else Decision.ALLOW,
            reason=(
                "Redacted " + ", ".join(f"{n} {k}" for k, n in sorted(dlp.redactions.items()))
                if dlp.redacted
                else verdict.reason
            ),
            reason_code=(
                "sensitive_data_redacted"
                if dlp.redacted
                else ("content_sanitized" if modified else "ok")
            ),
            checks={
                "firewall": CheckOutcome.PASS,
                "dlp": CheckOutcome.FAIL if dlp.redacted else CheckOutcome.PASS,
            },
            sanitized_text=dlp.text,
            redactions=dict(dlp.redactions),
            categories=verdict.categories,
            **self._base(event),
        )


def _intel_check(match) -> CheckOutcome:
    """A threat-intel checkpoint: FAIL when a known attack pattern matched."""
    return CheckOutcome.FAIL if match is not None else CheckOutcome.PASS


@lru_cache
def get_security_engine() -> SecurityEngine:
    """Return the process-wide security engine (shares the live engines)."""
    return SecurityEngine()

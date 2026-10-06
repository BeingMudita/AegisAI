"""The AegisAI Python SDK.

Wrap any agent in the full AegisAI pipeline with a few lines::

    from aegisai import SecureAgent

    agent = SecureAgent("FinanceAgent", policy="aegis.yaml")
    result = agent.run("Summarize this month's invoices")
    print(result.decision, result.answer)

Or use the primitives directly around your own model / framework::

    from aegisai import AegisGuard

    guard = AegisGuard("FinanceAgent")
    if guard.inspect_input(user_text).allowed:
        decision = guard.authorize_tool("FinanceAgent", "send_email", {"to": addr})
        safe = guard.scan_output(model_output).text

Nothing here is a new security control — it calls the same firewall, trust
engine, tool gateway, DLP and agent runtime the dashboard uses.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.agents.runtime import REFUSAL, get_runtime
from app.agents.schemas import AgentTurn
from app.database.enums import ToolRequestStatus
from app.firewall.dlp import redact
from app.firewall.scanner import get_firewall
from app.firewall.schemas import ContentChannel, FirewallAction, FirewallVerdict
from app.platform.policyfile import AegisFile
from app.platform.policyfile import apply as apply_policy
from app.policies.schemas import AgentPolicy
from app.policies.store import register_policy
from app.tools.gateway import get_tool_gateway
from app.tools.schemas import ToolCallResult

Decision = Literal["ALLOW", "FLAG", "BLOCK"]


def _decision_of(turn: AgentTurn) -> Decision:
    """ALLOW / FLAG / BLOCK for a turn — the same rule the dashboard uses."""
    denied = any(
        c.status == ToolRequestStatus.DENIED or c.output_action == FirewallAction.BLOCK
        for c in turn.tool_calls
    )
    if turn.blocked or denied:
        return "BLOCK"
    flagged = any(e.status == "flagged" for e in turn.trace) or any(
        c.output_action == FirewallAction.FLAG for c in turn.tool_calls
    )
    return "FLAG" if flagged else "ALLOW"


class ToolDecision(BaseModel):
    """What the gateway decided about one tool call in a turn."""

    tool: str
    status: str
    checkpoint: str | None = None  # the checkpoint that refused it, if any
    reason: str
    output_withheld: bool = False


class TraceStep(BaseModel):
    stage: str
    status: str
    detail: str


class SecureResult(BaseModel):
    """The outcome of a guarded run — safe to serialize and return to a caller."""

    agent: str
    session_id: str
    answer: str
    blocked: bool
    decision: Decision
    trace: list[TraceStep] = Field(default_factory=list)
    tool_calls: list[ToolDecision] = Field(default_factory=list)
    redactions: dict[str, int] = Field(default_factory=dict)
    duration_ms: float = 0.0

    @property
    def ok(self) -> bool:
        """True when nothing was blocked (the answer may still be sanitized)."""
        return self.decision != "BLOCK"

    @classmethod
    def from_turn(cls, turn: AgentTurn) -> SecureResult:
        tool_calls = []
        for c in turn.tool_calls:
            failed = next((ck.checkpoint for ck in c.checks if not ck.passed), None)
            tool_calls.append(
                ToolDecision(
                    tool=c.tool,
                    status=c.status.value,
                    checkpoint=failed,
                    reason=c.decision_reason,
                    output_withheld=c.output_action == FirewallAction.BLOCK,
                )
            )
        return cls(
            agent=turn.agent,
            session_id=turn.session_id,
            answer=turn.answer,
            blocked=turn.blocked,
            decision=_decision_of(turn),
            trace=[TraceStep(stage=e.stage, status=e.status, detail=e.detail) for e in turn.trace],
            tool_calls=tool_calls,
            redactions=dict(turn.redactions),
            duration_ms=turn.duration_ms,
        )


def _apply_policy(policy: object) -> None:
    """Register a policy given as a path, an AgentPolicy or an AegisFile."""
    if policy is None:
        return
    if isinstance(policy, AgentPolicy):
        register_policy(policy)
    elif isinstance(policy, AegisFile):
        policy.apply()
    else:  # a path to an aegis.yaml
        apply_policy(policy)  # type: ignore[arg-type]


class SecureAgent:
    """An agent whose every turn runs through the full AegisAI pipeline."""

    def __init__(self, name: str, policy: object | None = None) -> None:
        self.name = name
        _apply_policy(policy)

    def run(
        self,
        message: str,
        *,
        history: list[tuple[str, str]] | None = None,
        session_id: str | None = None,
    ) -> SecureResult:
        """Run one guarded turn and return a :class:`SecureResult`."""
        turn = get_runtime().run_turn(
            agent=self.name,
            session_id=session_id or f"sdk-{uuid4().hex[:12]}",
            message=message,
            history=history or [],
        )
        return SecureResult.from_turn(turn)


class OutputScan(BaseModel):
    """The result of screening a piece of outbound text."""

    action: FirewallAction
    text: str  # sanitized + DLP-redacted
    injection: bool  # an injection was found and removed
    categories: list[str] = Field(default_factory=list)
    redactions: dict[str, int] = Field(default_factory=dict)


class AegisGuard:
    """Framework-agnostic security primitives around your own agent / model."""

    def __init__(self, agent: str | None = None) -> None:
        self.agent = agent
        self._firewall = get_firewall()
        self._gateway = get_tool_gateway()

    def inspect_input(self, text: str, agent: str | None = None) -> FirewallVerdict:
        """Screen untrusted input (a user message) for prompt injection."""
        return self._firewall.inspect(
            text, ContentChannel.USER_INPUT, agent=agent or self.agent, context="sdk input"
        )

    def authorize_tool(
        self, agent: str, tool: str, arguments: dict | None = None
    ) -> ToolCallResult:
        """Pre-flight a tool call through the deny-by-default gateway (no execution)."""
        return self._gateway.authorize(agent, tool, arguments or {})

    def scan_output(self, text: str, agent: str | None = None, *, pii: bool = True) -> OutputScan:
        """Screen outbound text: strip injections, then redact secrets/PII via DLP."""
        verdict = self._firewall.inspect(
            text, ContentChannel.TOOL_OUTPUT, agent=agent or self.agent, context="sdk output"
        )
        cleaned = (
            self._firewall.sanitize(text, verdict)
            if verdict.action != FirewallAction.ALLOW
            else text
        )
        dlp = redact(cleaned, pii=pii)
        return OutputScan(
            action=verdict.action,
            text=dlp.text,
            injection=verdict.action != FirewallAction.ALLOW,
            categories=verdict.categories,
            redactions=dict(dlp.redactions),
        )


class AegisMiddleware:
    """Wrap an arbitrary ``Callable[[str], str]`` agent in input/output security.

    The wrapped agent can be from any framework — LangChain, a raw LLM call, a
    custom function. AegisAI screens the input, refuses an injection before the
    agent ever sees it, and screens the agent's output on the way out::

        chain = AegisMiddleware(my_agent.invoke, name="FinanceAgent", policy="aegis.yaml")
        result = chain.run("Summarize invoices")
    """

    def __init__(
        self, agent_fn: Callable[[str], str], name: str, policy: object | None = None
    ) -> None:
        self.agent_fn = agent_fn
        self.name = name
        self.guard = AegisGuard(name)
        _apply_policy(policy)

    def run(self, message: str, *, session_id: str | None = None) -> SecureResult:
        sid = session_id or f"mw-{uuid4().hex[:12]}"
        verdict = self.guard.inspect_input(message, self.name)
        if verdict.action == FirewallAction.BLOCK:
            return SecureResult(
                agent=self.name,
                session_id=sid,
                answer=REFUSAL,
                blocked=True,
                decision="BLOCK",
                trace=[
                    TraceStep(stage="input_firewall", status="blocked", detail=verdict.reason)
                ],
            )
        raw = self.agent_fn(message)
        scan = self.guard.scan_output(raw, self.name)
        decision: Decision = (
            "ALLOW"
            if verdict.action == FirewallAction.ALLOW and scan.action == FirewallAction.ALLOW
            else "BLOCK"
            if scan.action == FirewallAction.BLOCK
            else "FLAG"
        )
        return SecureResult(
            agent=self.name,
            session_id=sid,
            answer=scan.text,
            blocked=False,
            decision=decision,
            trace=[
                TraceStep(
                    stage="input_firewall",
                    status=verdict.action.value.lower(),
                    detail=verdict.reason,
                ),
                TraceStep(
                    stage="output_guard",
                    status="redacted" if (scan.injection or scan.redactions) else "passed",
                    detail=f"{scan.action.value} on agent output.",
                ),
            ],
            redactions=scan.redactions,
        )

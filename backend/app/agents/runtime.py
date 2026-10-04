"""The agent runtime — a LangGraph workflow with a security checkpoint at
every edge.

    START → guard_input ─┬─(blocked)──────────────────────────────▶ END
                         └→ retrieve → plan ─┬─(tool)→ act ─┐
                                    ▲        │              │
                                    │        └──────────────┘ (loop ≤ AGENT_MAX_STEPS)
                                    │        └─(answer)→ respond → guard_output → END

* guard_input  — suspension check, firewall on the user message
* retrieve     — guarded RAG (policy + trust gated, chunks screened)
* plan / act   — the brain proposes, the tool gateway disposes
* guard_output — DLP and an exfiltration scan on the final answer
"""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import lru_cache
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.brain import AgentBrain, get_brain
from app.agents.schemas import AgentAction, AgentTurn, TraceEntry, TurnContext
from app.config import get_settings
from app.database.enums import SecurityEventType, SecuritySeverity, SubjectType
from app.firewall.dlp import redact
from app.firewall.scanner import PromptFirewall, get_firewall
from app.firewall.schemas import ContentChannel, FirewallAction
from app.policies.config import get_global_config
from app.policies.engine import PolicyEngine
from app.policies.store import get_policy
from app.rag.knowledge_base import KnowledgeBase, get_knowledge_base
from app.rag.schemas import DroppedChunk, RetrievedChunk
from app.telemetry.store import get_audit_log
from app.tools.gateway import ToolGateway, get_tool_gateway
from app.tools.schemas import ToolCallResult
from app.trust.engine import TrustEngine, get_trust_engine
from app.trust.scoring import TrustSignal

REFUSAL = (
    "I can't help with that request — it was blocked by AegisAI's prompt-injection firewall. "
    "The attempt has been logged."
)
SUSPENDED = (
    "This agent is suspended because its trust score is too low. An administrator must review it."
)


class AgentState(TypedDict, total=False):
    progress: Callable[[TraceEntry], None] | None
    agent: str
    session_id: str
    message: str
    safe_message: str
    history: list[tuple[str, str]]
    blocked: bool
    context: list[RetrievedChunk]
    dropped: list[DroppedChunk]
    steps: list[ToolCallResult]
    pending: AgentAction | None
    answer: str
    redactions: dict[str, int]
    trace: list[TraceEntry]


class AgentRuntime:
    def __init__(
        self,
        *,
        brain: AgentBrain,
        firewall: PromptFirewall,
        trust: TrustEngine,
        gateway: ToolGateway,
        knowledge_base: KnowledgeBase,
        max_steps: int = 3,
    ) -> None:
        self.brain = brain
        self.firewall = firewall
        self.trust = trust
        self.gateway = gateway
        self.kb = knowledge_base
        self.max_steps = max_steps
        self.graph = self._build()

    # ---------------------------------------------------------------- graph
    def _build(self) -> Any:
        g = StateGraph(AgentState)
        for name, stage, node in [
            ("guard_input", "input_firewall", self.guard_input),
            ("retrieve", "retrieval", self.retrieve),
            ("plan", "plan", self.plan),
            ("act", "tool", self.act),
            ("respond", "respond", self.respond),
            ("guard_output", "output_guard", self.guard_output),
        ]:
            g.add_node(name, self._observed(stage, node))

        g.add_edge(START, "guard_input")
        g.add_conditional_edges(
            "guard_input", lambda s: END if s.get("blocked") else "retrieve", ["retrieve", END]
        )
        g.add_edge("retrieve", "plan")
        g.add_conditional_edges(
            "plan", lambda s: "act" if s.get("pending") else "respond", ["act", "respond"]
        )
        g.add_edge("act", "plan")
        g.add_edge("respond", "guard_output")
        g.add_edge("guard_output", END)
        return g.compile()

    @staticmethod
    def _observed(stage: str, node: Callable[[AgentState], AgentState]) -> Callable:
        """Publish real node boundaries without exposing unfinished model output."""

        def run(state: AgentState) -> AgentState:
            callback = state.get("progress")
            if callback:
                callback(TraceEntry(stage=stage, status="running", detail="Processing"))
            result = node(state)
            if callback:
                entries = result.get("trace", [])
                entry = (
                    entries[-1]
                    if entries and entries[-1].stage == stage
                    else TraceEntry(stage=stage, status="passed", detail="Stage completed.")
                )
                # Progress exposes status only; detailed evidence stays in the final guarded turn.
                callback(TraceEntry(stage=stage, status=entry.status, detail="Stage completed."))
            return result

        return run

    @staticmethod
    def _trace(state: AgentState, *entries: TraceEntry) -> list[TraceEntry]:
        return [*state.get("trace", []), *entries]

    def _context(self, state: AgentState) -> TurnContext:
        agent = state["agent"]
        return TurnContext(
            agent=agent,
            message=state.get("safe_message", state["message"]),
            tools=self.gateway.available_tools(agent),
            context=state.get("context", []),
            steps=state.get("steps", []),
            history=state.get("history", []),
        )

    # ---------------------------------------------------------------- nodes
    def guard_input(self, state: AgentState) -> AgentState:
        agent, session_id, message = state["agent"], state["session_id"], state["message"]

        standing = self.trust.evaluate(
            SubjectType.AGENT, agent, required=0.0, action="start a turn"
        )
        if not standing.allowed:
            return {
                "blocked": True,
                "answer": SUSPENDED,
                "trace": self._trace(
                    state,
                    TraceEntry(stage="input_firewall", status="blocked", detail=standing.reason),
                ),
            }

        verdict = self.firewall.inspect(
            message,
            ContentChannel.USER_INPUT,
            agent=agent,
            session_id=session_id,
            context="user message",
        )
        data = {
            "score": verdict.score,
            "categories": verdict.categories,
            "rules": [m.rule_id for m in verdict.matches],
        }
        if verdict.action == FirewallAction.BLOCK:
            self.trust.observe(
                SubjectType.AGENT,
                agent,
                TrustSignal.FIREWALL_BLOCK,
                rationale="Blocked prompt injection in user input",
                session_id=session_id,
            )
            return {
                "blocked": True,
                "answer": REFUSAL,
                "trace": self._trace(
                    state,
                    TraceEntry(
                        stage="input_firewall", status="blocked", detail=verdict.reason, data=data
                    ),
                ),
            }
        if verdict.action == FirewallAction.FLAG:
            # Suspicious but not conclusive: let it through unchanged (rewriting a
            # user's request would garble it) — it is audited, costs trust, and
            # every action it leads to still has to pass the tool gateway.
            self.trust.observe(
                SubjectType.AGENT,
                agent,
                TrustSignal.FIREWALL_FLAG,
                rationale="Suspicious user input",
                session_id=session_id,
            )
            return {
                "safe_message": message,
                "trace": self._trace(
                    state,
                    TraceEntry(
                        stage="input_firewall", status="flagged", detail=verdict.reason, data=data
                    ),
                ),
            }
        return {
            "safe_message": message,
            "trace": self._trace(
                state, TraceEntry(stage="input_firewall", status="passed", detail=verdict.reason)
            ),
        }

    def retrieve(self, state: AgentState) -> AgentState:
        agent = state["agent"]
        policy = get_policy(agent)
        if policy is None or not PolicyEngine(policy).can_use_tool("search_documents").allowed:
            return {
                "trace": self._trace(
                    state,
                    TraceEntry(
                        stage="retrieval",
                        status="skipped",
                        detail="Policy does not allow knowledge-base search.",
                    ),
                )
            }

        tool_policy = get_global_config().tool("search_documents")
        required = tool_policy.required_trust if tool_policy else None
        decision = self.trust.evaluate(
            SubjectType.AGENT, agent, required=required, action="search documents"
        )
        if not decision.allowed:
            return {
                "trace": self._trace(
                    state, TraceEntry(stage="retrieval", status="denied", detail=decision.reason)
                )
            }

        result = self.kb.retrieve(
            state["safe_message"], agent=agent, session_id=state["session_id"]
        )
        sanitized = sum(c.sanitized for c in result.chunks)
        detail = f"{len(result.chunks)} chunk(s) used, {len(result.dropped)} dropped"
        if sanitized:
            detail += f", {sanitized} sanitized"
        return {
            "context": result.chunks,
            "dropped": result.dropped,
            "trace": self._trace(
                state,
                TraceEntry(
                    stage="retrieval",
                    status="passed",
                    detail=detail + ".",
                    data={
                        "sources": sorted({c.source for c in result.chunks}),
                        "dropped": [f"{d.source}: {d.reason}" for d in result.dropped],
                    },
                ),
            ),
        }

    def plan(self, state: AgentState) -> AgentState:
        if len(state.get("steps", [])) >= self.max_steps:
            return {
                "pending": None,
                "trace": self._trace(
                    state,
                    TraceEntry(
                        stage="plan",
                        status="skipped",
                        detail="Tool step limit reached; compose answer.",
                    ),
                ),
            }
        action = self.brain.decide(self._context(state))
        if action.kind != "tool" or not action.tool:
            return {
                "pending": None,
                "trace": self._trace(
                    state,
                    TraceEntry(
                        stage="plan", status="passed", detail="No further tool action needed."
                    ),
                ),
            }
        return {
            "pending": action,
            "trace": self._trace(
                state,
                TraceEntry(
                    stage="plan",
                    status="passed",
                    detail=f"Proposed {action.tool}: {action.thought}",
                    data={"tool": action.tool, "arguments": action.arguments},
                ),
            ),
        }

    def act(self, state: AgentState) -> AgentState:
        action = state["pending"]
        assert action is not None and action.tool is not None
        result = self.gateway.execute(
            state["agent"], action.tool, action.arguments, session_id=state["session_id"]
        )
        status = {"EXECUTED": "executed", "DENIED": "denied", "PENDING": "pending"}.get(
            result.status.value, "failed"
        )
        failed_at = next((c.checkpoint for c in result.checks if not c.passed), None)
        return {
            "pending": None,
            "steps": [*state.get("steps", []), result],
            "trace": self._trace(
                state,
                TraceEntry(
                    stage="tool",
                    status=status,
                    detail=f"{action.tool}: {result.decision_reason}",
                    data={
                        "tool": action.tool,
                        "checkpoint": failed_at,
                        "output_action": result.output_action,
                    },
                ),
            ),
        }

    def respond(self, state: AgentState) -> AgentState:
        answer = self.brain.compose(self._context(state))
        return {
            "answer": answer,
            "trace": self._trace(
                state,
                TraceEntry(
                    stage="respond",
                    status="passed",
                    detail=f"Answer composed by {self.brain.name}.",
                ),
            ),
        }

    def guard_output(self, state: AgentState) -> AgentState:
        agent, answer = state["agent"], state.get("answer", "")
        policy = get_policy(agent)
        dlp = redact(answer, pii=bool(policy and policy.sensitive_data))
        answer = dlp.text

        # Only exfiltration channels (e.g. markdown image beacons) matter here;
        # the answer quoting already-screened context is expected.
        verdict = self.firewall.scan(answer, ContentChannel.TOOL_OUTPUT)
        exfil = "DATA_EXFILTRATION" in verdict.categories
        if exfil:
            answer = self.firewall.sanitize(answer, verdict)
            get_audit_log().record_event(
                event_type=SecurityEventType.PROMPT_INJECTION,
                severity=SecuritySeverity.HIGH,
                source="agent",
                agent=agent,
                session_id=state["session_id"],
                description="Exfiltration attempt removed from the agent's answer.",
                details={"rules": [m.rule_id for m in verdict.matches]},
            )

        parts = []
        if dlp.redacted:
            parts.append(
                "Redacted " + ", ".join(f"{n} {k}" for k, n in sorted(dlp.redactions.items()))
            )
        if exfil:
            parts.append("removed an exfiltration link")
        detail = "; ".join(parts) + "." if parts else "No sensitive data in the answer."
        changed = bool(parts)
        return {
            "answer": answer,
            "redactions": dict(dlp.redactions),
            "trace": self._trace(
                state,
                TraceEntry(
                    stage="output_guard", status="redacted" if changed else "passed", detail=detail
                ),
            ),
        }

    # ------------------------------------------------------------------ run
    def run_turn(
        self,
        *,
        agent: str,
        session_id: str,
        message: str,
        history: list[tuple[str, str]] | None = None,
        progress: Callable[[TraceEntry], None] | None = None,
    ) -> AgentTurn:
        started = time.perf_counter()
        final: AgentState = self.graph.invoke(
            {
                "agent": agent,
                "session_id": session_id,
                "message": message,
                "history": history or [],
                "progress": progress,
            },
            config={"recursion_limit": 6 + 2 * self.max_steps},
        )
        return AgentTurn(
            session_id=session_id,
            agent=agent,
            message=message,
            answer=final.get("answer", ""),
            blocked=bool(final.get("blocked")),
            brain=self.brain.name,
            trace=final.get("trace", []),
            tool_calls=final.get("steps", []),
            context=final.get("context", []),
            dropped=final.get("dropped", []),
            redactions=final.get("redactions", {}),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )


@lru_cache
def get_runtime() -> AgentRuntime:
    """Return the process-wide agent runtime."""
    return AgentRuntime(
        brain=get_brain(),
        firewall=get_firewall(),
        trust=get_trust_engine(),
        gateway=get_tool_gateway(),
        knowledge_base=get_knowledge_base(),
        max_steps=get_settings().agent_max_steps,
    )

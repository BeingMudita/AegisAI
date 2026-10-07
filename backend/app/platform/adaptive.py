"""Runtime adaptive security — observe behavior, update risk, adapt enforcement.

The static pipeline is ``Agent → Aegis → Decision``. This adds the runtime loop::

    Agent → Aegis → Decision → observe behavior → update risk → adapt enforcement

Each tool call an agent makes is observed. Behaviour that deviates from the
agent's established baseline — a tool it has never used, a sensitive read
followed by an external send, a burst of calls — costs trust. As trust falls the
agent moves through postures, and the proxy enforces each posture more strictly::

    NORMAL ──▶ SUSPICIOUS ──▶ RESTRICTED ──▶ QUARANTINED
     (all)      (approve      (block ext /     (block
                 ext/high)     high-impact)     everything)

The trust score itself still lives in the trust engine (so the dashboard, audit
log and tool gateway all see the same number); this module only observes,
penalises, and overlays posture-based enforcement on top of a decision.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from enum import Enum

from pydantic import BaseModel, Field

from app.database.enums import SecurityEventType, SecuritySeverity, SubjectType
from app.platform.protocol.schemas import AegisDecision, CheckOutcome, Decision
from app.telemetry.store import get_audit_log
from app.tools.gateway import get_tool_gateway
from app.trust.engine import TrustEngine, get_trust_engine
from app.trust.scoring import TrustSignal

# How many of an agent's first tool calls establish its "normal" tool set.
_BASELINE_CALLS = 5
_BURST_WINDOW_S = 60.0
_BURST_LIMIT = 10
_RECENT = 40


class AgentPosture(str, Enum):
    NORMAL = "NORMAL"
    SUSPICIOUS = "SUSPICIOUS"
    RESTRICTED = "RESTRICTED"
    QUARANTINED = "QUARANTINED"


# Trust floors for each posture, highest first.
_POSTURE_FLOORS: tuple[tuple[float, AgentPosture], ...] = (
    (0.60, AgentPosture.NORMAL),
    (0.40, AgentPosture.SUSPICIOUS),
    (0.20, AgentPosture.RESTRICTED),
    (0.0, AgentPosture.QUARANTINED),
)


def posture_for(score: float) -> AgentPosture:
    for floor, posture in _POSTURE_FLOORS:
        if score >= floor:
            return posture
    return AgentPosture.QUARANTINED


def _host(value: str) -> str:
    """Best-effort host extraction from a URL or email argument."""
    from urllib.parse import urlparse

    value = value.strip()
    if not value:
        return ""
    if "@" in value and "://" not in value:
        return value.rsplit("@", 1)[-1].lower()
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return (parsed.hostname or "").lower()


class BehaviorEvent(BaseModel):
    tool: str
    external: bool
    sensitive: bool
    allowed: bool
    host: str | None = None  # destination host for external tool calls
    anomalies: list[str] = Field(default_factory=list)


class AgentStateReport(BaseModel):
    agent: str
    trust_score: float
    posture: AgentPosture
    baseline_tools: list[str]
    calls_observed: int
    anomalies: int
    recent: list[BehaviorEvent] = Field(default_factory=list)


class _AgentWindow:
    def __init__(self) -> None:
        self.baseline: set[str] = set()
        self.calls = 0
        self.anomaly_count = 0
        self.times: deque[float] = deque(maxlen=_BURST_LIMIT * 2)
        self.recent: deque[BehaviorEvent] = deque(maxlen=_RECENT)
        self.sensitive_recent = False  # a sensitive read happened recently in this window


class AdaptiveMonitor:
    """Observes tool calls, penalises deviation, and overlays posture enforcement."""

    def __init__(self, trust: TrustEngine | None = None) -> None:
        self._trust = trust or get_trust_engine()
        self._agents: dict[str, _AgentWindow] = defaultdict(_AgentWindow)
        self._lock = threading.Lock()

    # ----------------------------------------------------------- inspection
    def posture(self, agent: str) -> AgentPosture:
        return posture_for(self._trust.score(SubjectType.AGENT, agent))

    def state(self, agent: str) -> AgentStateReport:
        with self._lock:
            w = self._agents.get(agent)
            score = self._trust.score(SubjectType.AGENT, agent)
            return AgentStateReport(
                agent=agent,
                trust_score=round(score, 4),
                posture=posture_for(score),
                baseline_tools=sorted(w.baseline) if w else [],
                calls_observed=w.calls if w else 0,
                anomalies=w.anomaly_count if w else 0,
                recent=list(w.recent) if w else [],
            )

    def recent_events(self, agent: str) -> list[BehaviorEvent]:
        """Recent observed tool calls (used by Autopilot to mine runtime behaviour)."""
        with self._lock:
            w = self._agents.get(agent)
            return list(w.recent) if w else []

    def reset(self, agent: str) -> None:
        """Lift a quarantine / restore the baseline (an administrator action)."""
        with self._lock:
            self._agents.pop(agent, None)

    def clear(self) -> None:
        with self._lock:
            self._agents.clear()

    # -------------------------------------------------------------- observe
    def _tool_facts(self, tool: str) -> tuple[bool, bool, bool, str | None]:
        """(external, sensitive, high_impact, domain_arg) for a tool."""
        info = next((t for t in get_tool_gateway().describe() if t.name == tool), None)
        if info is None:
            return False, False, False, None
        external = info.domain_checked_argument is not None
        sensitive = bool(info.data_category)
        high_impact = info.risk_level.value in {"HIGH", "CRITICAL"} or external
        return external, sensitive, high_impact, info.domain_checked_argument

    def _detect(self, w: _AgentWindow, tool: str, external: bool, sensitive: bool) -> list[str]:
        anomalies: list[str] = []
        if w.calls >= _BASELINE_CALLS and tool not in w.baseline:
            anomalies.append("new_tool")
        if external and w.sensitive_recent:
            anomalies.append("exfiltration_pattern")
        now = time.monotonic()
        w.times.append(now)
        if sum(1 for t in w.times if now - t <= _BURST_WINDOW_S) > _BURST_LIMIT:
            anomalies.append("burst")
        return anomalies

    def apply(
        self,
        agent: str,
        tool: str,
        decision: AegisDecision,
        arguments: dict | None = None,
    ) -> AegisDecision:
        """Observe a tool decision, update trust, and overlay posture enforcement.

        Returns the decision to act on — possibly tightened (ALLOW→APPROVAL,
        ALLOW→BLOCK) when the agent's posture has degraded.
        """
        external, sensitive, high_impact, domain_arg = self._tool_facts(tool)
        host = _host(str((arguments or {}).get(domain_arg, ""))) if domain_arg else None
        with self._lock:
            w = self._agents[agent]
            anomalies = self._detect(w, tool, external, sensitive)
            if w.calls < _BASELINE_CALLS and decision.decision != Decision.BLOCK:
                w.baseline.add(tool)
            w.calls += 1
            if sensitive and decision.decision != Decision.BLOCK:
                w.sensitive_recent = True
            w.anomaly_count += len(anomalies)
            w.recent.append(
                BehaviorEvent(
                    tool=tool,
                    external=external,
                    sensitive=sensitive,
                    allowed=decision.decision != Decision.BLOCK,
                    host=host or None,
                    anomalies=anomalies,
                )
            )

        for anomaly in anomalies:
            self._trust.observe(
                SubjectType.AGENT,
                agent,
                TrustSignal.BEHAVIORAL_ANOMALY,
                rationale=f"{anomaly} on {tool}",
            )
            get_audit_log().record_event(
                event_type=SecurityEventType.ANOMALY,
                severity=SecuritySeverity.HIGH
                if anomaly == "exfiltration_pattern"
                else SecuritySeverity.MEDIUM,
                source="adaptive",
                agent=agent,
                description=f"Behavioral anomaly '{anomaly}' on {tool}",
                details={"tool": tool, "anomaly": anomaly},
            )

        if decision.decision == Decision.BLOCK:
            return decision
        return self._overlay(agent, tool, external, high_impact, decision)

    def _overlay(
        self,
        agent: str,
        tool: str,
        external: bool,
        high_impact: bool,
        decision: AegisDecision,
    ) -> AegisDecision:
        posture = self.posture(agent)
        risky = external or high_impact
        updated = decision.model_copy(deep=True)
        updated.trust_score = round(self._trust.score(SubjectType.AGENT, agent), 4)

        if posture == AgentPosture.QUARANTINED:
            return _tighten(
                updated, Decision.BLOCK, "posture_quarantined",
                f"Agent is QUARANTINED (trust {updated.trust_score}); all tools are blocked.",
            )
        if posture == AgentPosture.RESTRICTED and risky:
            return _tighten(
                updated, Decision.BLOCK, "posture_restricted",
                f"Agent is RESTRICTED; '{tool}' is blocked until trust recovers.",
            )
        if posture == AgentPosture.SUSPICIOUS and risky and updated.decision != Decision.BLOCK:
            return _tighten(
                updated, Decision.APPROVAL, "posture_review",
                f"Agent is SUSPICIOUS; '{tool}' now requires human approval.",
            )
        return updated


def _tighten(
    decision: AegisDecision, new: Decision, code: str, reason: str
) -> AegisDecision:
    decision.decision = new
    decision.reason = reason
    decision.reason_code = code
    decision.checks["posture"] = CheckOutcome.FAIL
    return decision


_monitor = AdaptiveMonitor()


def get_adaptive_monitor() -> AdaptiveMonitor:
    """Return the process-wide adaptive monitor."""
    return _monitor

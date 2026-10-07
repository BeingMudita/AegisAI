"""Pure trust-scoring rules — score↔level mapping and how signals move a score.

Kept free of state and I/O so the arithmetic is easy to reason about and test.

Update rule:
  * penalties subtract their full magnitude (trust is lost quickly);
  * rewards are scaled by the remaining headroom ``(1 - score)``, so trust is
    regained slowly and asymptotically approaches 1.
"""

from __future__ import annotations

from enum import Enum

from app.database.enums import ToolRiskLevel, TrustLevel

# Lower bounds for each level, highest first.
_LEVEL_FLOORS: tuple[tuple[float, TrustLevel], ...] = (
    (0.85, TrustLevel.VERIFIED),
    (0.60, TrustLevel.HIGH),
    (0.40, TrustLevel.MEDIUM),
    (0.20, TrustLevel.LOW),
    (0.0, TrustLevel.UNTRUSTED),
)

# Starting score for a document source by its declared trust level.
SOURCE_BASE_SCORE: dict[TrustLevel, float] = {
    TrustLevel.VERIFIED: 0.95,
    TrustLevel.HIGH: 0.8,
    TrustLevel.MEDIUM: 0.6,
    TrustLevel.LOW: 0.35,
    TrustLevel.UNTRUSTED: 0.1,
}

# Default minimum agent trust to use a tool, by the tool's risk level
# (used when the policy file does not give the tool an explicit min_trust).
TOOL_RISK_MIN_TRUST: dict[ToolRiskLevel, float] = {
    ToolRiskLevel.LOW: 0.3,
    ToolRiskLevel.MEDIUM: 0.5,
    ToolRiskLevel.HIGH: 0.7,
    ToolRiskLevel.CRITICAL: 0.9,
}

INITIAL_AGENT_TRUST = 0.75
INITIAL_TOOL_TRUST = 0.8
SUSPENSION_THRESHOLD = 0.2  # agents below this are refused outright


class TrustSignal(str, Enum):
    """Observations that move a subject's trust score."""

    CLEAN_ACTION = "CLEAN_ACTION"
    FIREWALL_FLAG = "FIREWALL_FLAG"
    FIREWALL_BLOCK = "FIREWALL_BLOCK"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    TOOL_DENIED = "TOOL_DENIED"
    INJECTED_CONTENT = "INJECTED_CONTENT"  # a source served injected content
    TOOL_FAILURE = "TOOL_FAILURE"
    BEHAVIORAL_ANOMALY = "BEHAVIORAL_ANOMALY"  # runtime behavior deviated from the baseline


SIGNAL_DELTA: dict[TrustSignal, float] = {
    TrustSignal.CLEAN_ACTION: +0.04,
    TrustSignal.FIREWALL_FLAG: -0.05,
    TrustSignal.FIREWALL_BLOCK: -0.15,
    TrustSignal.POLICY_VIOLATION: -0.10,
    TrustSignal.TOOL_DENIED: -0.03,
    TrustSignal.INJECTED_CONTENT: -0.20,
    TrustSignal.TOOL_FAILURE: -0.02,
    TrustSignal.BEHAVIORAL_ANOMALY: -0.18,
}


def clamp(score: float) -> float:
    return max(0.0, min(1.0, score))


def level_for(score: float) -> TrustLevel:
    """Map a 0–1 score to a :class:`TrustLevel`."""
    for floor, level in _LEVEL_FLOORS:
        if score >= floor:
            return level
    return TrustLevel.UNTRUSTED


def apply_signal(score: float, signal: TrustSignal) -> float:
    """Return the new score after observing ``signal``."""
    delta = SIGNAL_DELTA[signal]
    if delta >= 0:
        return round(clamp(score + delta * (1.0 - score)), 4)
    return round(clamp(score + delta), 4)

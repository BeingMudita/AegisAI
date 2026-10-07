"""The decision half of the Aegis Security Event Protocol.

An :class:`AegisEvent` goes in; an :class:`AegisDecision` comes out. The decision
is the single shape every adapter understands — it carries the verdict, a
human-readable reason, a machine-readable ``reason_code``, a per-checkpoint
breakdown, and whatever transformed payload the caller should use instead of the
original (sanitized text, redaction counts, quarantined documents).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.platform.protocol.events import AegisEventType


class Decision(str, Enum):
    """What the caller should do with the event."""

    ALLOW = "ALLOW"  # proceed (payload may still be sanitized / redacted)
    FLAG = "FLAG"  # proceed, but the event was modified and audited
    BLOCK = "BLOCK"  # do not proceed
    APPROVAL = "APPROVAL"  # hold for a human decision before proceeding

    @property
    def permits(self) -> bool:
        """True when the action may go ahead (possibly in modified form)."""
        return self in {Decision.ALLOW, Decision.FLAG}


class CheckOutcome(str, Enum):
    """The result of one security checkpoint for this event."""

    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"  # not applicable to this event


class AegisDecision(BaseModel):
    """The engine's verdict on one event."""

    decision: Decision
    reason: str
    reason_code: str = "ok"
    event_type: AegisEventType
    agent: str
    session_id: str
    checks: dict[str, CheckOutcome] = Field(default_factory=dict)
    # Transformed payload the caller should use instead of the original.
    sanitized_text: str | None = None
    redactions: dict[str, int] = Field(default_factory=dict)
    categories: list[str] = Field(default_factory=list)
    quarantined: list[int] = Field(default_factory=list)  # RETRIEVAL: dropped doc indices
    trust_score: float | None = None

    @property
    def allowed(self) -> bool:
        """True when nothing was blocked (the payload may still be modified)."""
        return self.decision != Decision.BLOCK

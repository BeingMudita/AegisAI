"""The Aegis Security Event Protocol — the language every integration speaks.

    from app.platform.protocol import AegisEvent, get_security_engine

    engine = get_security_engine()
    decision = engine.evaluate(AegisEvent.tool_proposal("finance-agent", "send_email",
                                                         {"to": "attacker@gmail.com"}))
    print(decision.decision, decision.reason_code)  # Decision.BLOCK untrusted_external_destination
"""

from __future__ import annotations

from app.platform.protocol.adapters import AgentAdapter
from app.platform.protocol.engine import SecurityEngine, get_security_engine
from app.platform.protocol.events import (
    AegisEvent,
    AegisEventType,
    EventContext,
    RetrievedDocument,
    ToolCall,
)
from app.platform.protocol.schemas import AegisDecision, CheckOutcome, Decision

__all__ = [
    "AegisDecision",
    "AegisEvent",
    "AegisEventType",
    "AgentAdapter",
    "CheckOutcome",
    "Decision",
    "EventContext",
    "RetrievedDocument",
    "SecurityEngine",
    "ToolCall",
    "get_security_engine",
]

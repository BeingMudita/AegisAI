"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from __future__ import annotations

from app.database.base import Base
from app.database.models.core import (
    Agent,
    AgentSession,
    AgentTurnRow,
    Policy,
    SessionRun,
    Tenant,
    User,
)
from app.database.models.documents import (
    Document,
    DocumentChunk,
    DocumentSource,
    Embedding,
    IngestJobRow,
)
from app.database.models.security import (
    DecisionCounter,
    RateLimitHit,
    RedTeamRunRow,
    SecurityEvent,
    ToolDefinition,
    ToolRequest,
    TrustAssessment,
    TrustScoreRow,
    UsageBudget,
)

__all__ = [
    "Base",
    "Tenant",
    "User",
    "Agent",
    "Policy",
    "AgentSession",
    "SessionRun",
    "AgentTurnRow",
    "DocumentSource",
    "Document",
    "DocumentChunk",
    "Embedding",
    "IngestJobRow",
    "TrustAssessment",
    "TrustScoreRow",
    "DecisionCounter",
    "RateLimitHit",
    "RedTeamRunRow",
    "ToolDefinition",
    "ToolRequest",
    "SecurityEvent",
    "UsageBudget",
]

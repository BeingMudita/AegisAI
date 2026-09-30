"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from __future__ import annotations

from app.database.base import Base
from app.database.models.core import Agent, AgentSession, Policy, User
from app.database.models.documents import (
    Document,
    DocumentChunk,
    DocumentSource,
    Embedding,
)
from app.database.models.security import (
    SecurityEvent,
    ToolDefinition,
    ToolRequest,
    TrustAssessment,
)

__all__ = [
    "Base",
    "User",
    "Agent",
    "Policy",
    "AgentSession",
    "DocumentSource",
    "Document",
    "DocumentChunk",
    "Embedding",
    "TrustAssessment",
    "ToolDefinition",
    "ToolRequest",
    "SecurityEvent",
]

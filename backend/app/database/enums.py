"""Enumerations shared across database models."""

from __future__ import annotations

from enum import Enum


class AgentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISABLED = "DISABLED"


class SessionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class SourceType(str, Enum):
    FILE = "FILE"
    URL = "URL"
    DATABASE = "DATABASE"
    API = "API"
    MANUAL = "MANUAL"


class SubjectType(str, Enum):
    """What a trust assessment is about."""

    AGENT = "AGENT"
    SOURCE = "SOURCE"
    TOOL = "TOOL"


class TrustLevel(str, Enum):
    UNTRUSTED = "UNTRUSTED"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERIFIED = "VERIFIED"


class ToolRiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ToolRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


class SecurityEventType(str, Enum):
    PROMPT_INJECTION = "PROMPT_INJECTION"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    TRUST_DEGRADATION = "TRUST_DEGRADATION"
    TOOL_DENIED = "TOOL_DENIED"
    AUTH_FAILURE = "AUTH_FAILURE"
    ANOMALY = "ANOMALY"


class SecuritySeverity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

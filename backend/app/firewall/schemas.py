"""Pydantic schemas for the prompt-injection firewall."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class FirewallAction(str, Enum):
    ALLOW = "ALLOW"
    FLAG = "FLAG"  # suspicious — allowed through, but sanitized / audited
    BLOCK = "BLOCK"


class ContentChannel(str, Enum):
    """Where the scanned text came from.

    Text arriving through a data channel (retrieved documents, tool output) is
    never supposed to carry instructions, so the same pattern is weighted more
    heavily there than in direct user input (indirect prompt injection).
    """

    USER_INPUT = "USER_INPUT"
    RETRIEVED = "RETRIEVED"
    TOOL_OUTPUT = "TOOL_OUTPUT"
    TOOL_ARGUMENTS = "TOOL_ARGUMENTS"

    @property
    def is_indirect(self) -> bool:
        return self in {ContentChannel.RETRIEVED, ContentChannel.TOOL_OUTPUT}


class RuleMatch(BaseModel):
    """One detection rule that fired."""

    rule_id: str
    category: str
    weight: float
    excerpt: str
    start: int = -1  # span in the normalized text; -1 for signal-based rules
    end: int = -1


class FirewallVerdict(BaseModel):
    """The firewall's decision about a piece of text."""

    action: FirewallAction
    score: float = Field(ge=0.0, le=1.0)
    channel: ContentChannel
    matches: list[RuleMatch] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    reason: str

    @property
    def allowed(self) -> bool:
        return self.action != FirewallAction.BLOCK


class ScanRequest(BaseModel):
    text: str = Field(max_length=20_000)
    channel: ContentChannel = ContentChannel.USER_INPUT


class RuleInfo(BaseModel):
    rule_id: str
    category: str
    weight: float
    description: str

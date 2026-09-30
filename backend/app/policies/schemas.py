"""Pydantic schemas for agent policies and policy decisions."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentPolicy(BaseModel):
    """A declarative policy describing what a single agent may do.

    Matches the agent-policy JSON document, e.g.::

        {
          "agent": "FinanceAgent",
          "allowed_tools": ["search_documents", "read_database"],
          "blocked_tools": ["shell", "external_upload"],
          "allowed_domains": ["company.com"],
          "sensitive_data": ["customer_records", "credentials"]
        }
    """

    agent: str
    allowed_tools: list[str] = Field(default_factory=list)
    blocked_tools: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    sensitive_data: list[str] = Field(default_factory=list)


class PolicyDecision(BaseModel):
    """The result of evaluating a single action against a policy."""

    allowed: bool
    reason: str
    agent: str
    subject: str | None = None  # the tool name / domain / data category involved


class AgentAllowances(BaseModel):
    """A summary answer to: 'What is this agent allowed to do?'"""

    agent: str
    allowed_tools: list[str]
    blocked_tools: list[str]
    allowed_domains: list[str]
    sensitive_data: list[str]

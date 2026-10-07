"""The Aegis Security Event Protocol — the framework-neutral contract.

Every integration (OpenAI, LangGraph, MCP, a custom agent) is translated into
one of a handful of :class:`AegisEvent`s *before* it reaches the security engine.
The engine speaks only this language, so supporting a new framework means writing
a new **adapter** — never a new copy of the firewall / policy / trust logic::

    OpenAI ─────┐
    LangGraph ──┤
    MCP ────────┼──▶  AegisEvent  ──▶  SecurityEngine  ──▶  AegisDecision
    Node agent ─┤
    Custom ─────┘

Five event types cover an agent's interaction with the outside world:

    INPUT          an (untrusted) message arriving from a user
    RETRIEVAL      documents / chunks pulled from a data source
    TOOL_PROPOSAL  a tool the model wants to call, *before* it runs
    TOOL_RESULT    the output a tool produced, *before* the model sees it
    OUTPUT         the text about to be returned to the user

An event carries only the fields its type needs; the convenience constructors
(:meth:`AegisEvent.input`, :meth:`~AegisEvent.tool_proposal`, …) build a
well-formed event for each kind.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AegisEventType(str, Enum):
    """The kinds of interaction AegisAI can inspect."""

    INPUT = "INPUT"
    RETRIEVAL = "RETRIEVAL"
    TOOL_PROPOSAL = "TOOL_PROPOSAL"
    TOOL_RESULT = "TOOL_RESULT"
    OUTPUT = "OUTPUT"


class ToolCall(BaseModel):
    """A tool the model wants to call (or has just called)."""

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class RetrievedDocument(BaseModel):
    """One document / chunk returned by a retrieval step."""

    content: str
    source: str = "unknown"
    trust: float | None = None


class EventContext(BaseModel):
    """Caller-supplied hints. The engine treats these as advisory only — the
    authoritative trust score always comes from the trust engine."""

    trust_score: float | None = None
    model: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class AegisEvent(BaseModel):
    """A single, framework-neutral security event.

    Only the payload fields relevant to ``event_type`` are populated:

    ======================  ==========================================
    event_type              payload
    ======================  ==========================================
    ``INPUT`` / ``OUTPUT``  ``text``
    ``RETRIEVAL``           ``documents``
    ``TOOL_PROPOSAL``       ``tool``
    ``TOOL_RESULT``         ``tool`` + ``text`` (the tool's output)
    ======================  ==========================================
    """

    event_type: AegisEventType
    agent: str
    session_id: str = "proxy"
    text: str | None = None
    tool: ToolCall | None = None
    documents: list[RetrievedDocument] = Field(default_factory=list)
    context: EventContext = Field(default_factory=EventContext)

    # --------------------------------------------------------- constructors
    @classmethod
    def input(
        cls, agent: str, text: str, *, session_id: str = "proxy", **context: Any
    ) -> AegisEvent:
        return cls(
            event_type=AegisEventType.INPUT,
            agent=agent,
            session_id=session_id,
            text=text,
            context=EventContext(**context),
        )

    @classmethod
    def output(
        cls, agent: str, text: str, *, session_id: str = "proxy", **context: Any
    ) -> AegisEvent:
        return cls(
            event_type=AegisEventType.OUTPUT,
            agent=agent,
            session_id=session_id,
            text=text,
            context=EventContext(**context),
        )

    @classmethod
    def retrieval(
        cls,
        agent: str,
        documents: list[RetrievedDocument] | list[dict[str, Any]],
        *,
        session_id: str = "proxy",
        **context: Any,
    ) -> AegisEvent:
        docs = [
            d if isinstance(d, RetrievedDocument) else RetrievedDocument(**d) for d in documents
        ]
        return cls(
            event_type=AegisEventType.RETRIEVAL,
            agent=agent,
            session_id=session_id,
            documents=docs,
            context=EventContext(**context),
        )

    @classmethod
    def tool_proposal(
        cls,
        agent: str,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        session_id: str = "proxy",
        **context: Any,
    ) -> AegisEvent:
        return cls(
            event_type=AegisEventType.TOOL_PROPOSAL,
            agent=agent,
            session_id=session_id,
            tool=ToolCall(name=name, arguments=arguments or {}),
            context=EventContext(**context),
        )

    @classmethod
    def tool_result(
        cls,
        agent: str,
        name: str,
        output: str,
        *,
        arguments: dict[str, Any] | None = None,
        session_id: str = "proxy",
        **context: Any,
    ) -> AegisEvent:
        return cls(
            event_type=AegisEventType.TOOL_RESULT,
            agent=agent,
            session_id=session_id,
            tool=ToolCall(name=name, arguments=arguments or {}),
            text=output,
            context=EventContext(**context),
        )

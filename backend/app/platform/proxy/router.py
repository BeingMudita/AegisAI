"""The Aegis proxy router — ``/v1/proxy/*`` and ``/v1/chat/completions``.

    Existing Agent
          │  request
          ▼
    ┌───────────────────┐
    │    AEGIS PROXY    │
    │  normalize event  │
    │        ↓          │
    │  security engine  │
    │        ↓          │
    │  decision         │
    └─────────┬─────────┘
              ▼
       target LLM / API

Each endpoint does the same three things: normalize the incoming request into
:class:`AegisEvent`s, run them through the one
:class:`~app.platform.protocol.engine.SecurityEngine`, and act on the decision —
refuse, forward, or forward a sanitized version. No security logic lives here.

Mounted both in the standalone proxy app (:mod:`app.platform.proxy.server`) and
in the main AegisAI app, so ``/v1/proxy/*`` works in either. Auth reuses the
gateway's ``X-Aegis-Key`` / JWT scheme.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request

from app.platform.adapters import get_adapter
from app.platform.adapters.openai import OpenAIAdapter
from app.platform.gateway_api import require_gateway_access
from app.platform.protocol import AegisEvent
from app.platform.protocol.engine import get_security_engine
from app.platform.protocol.schemas import AegisDecision, Decision
from app.platform.proxy.server import DEFAULT_AGENT, Upstream
from app.platform.proxy.sessions import get_session_registry
from app.platform.proxy.transformer import (
    ProxyChatRequest,
    ProxyChatResponse,
    ProxyOutputRequest,
    ProxyToolRequest,
    first_block,
)

router = APIRouter(prefix="/v1", tags=["proxy"])

REFUSAL = (
    "I can't help with that — AegisAI's input firewall blocked the request. "
    "The attempt has been logged."
)


# ---------------------------------------------------------------- helpers
def _state(request: Request, name: str, default):
    return getattr(request.app.state, name, default)


def _session(agent: str, session_id: str | None) -> str:
    return get_session_registry().touch(agent, session_id).session_id


# --------------------------------------------------- proxy-native endpoints
@router.post("/proxy/tool", response_model=AegisDecision)
def proxy_tool(
    body: ProxyToolRequest, _principal: str = Depends(require_gateway_access)
) -> AegisDecision:
    """Authorize one tool call (the enforcement point for external agents).

    This never runs the tool — it is the deny-by-default gateway's dry-run
    authorization, surfaced through the event protocol. An external agent asks
    *"may I?"* before every tool call; AegisAI answers ALLOW / APPROVAL / BLOCK.
    """
    sid = _session(body.agent, body.session_id)
    event = AegisEvent.tool_proposal(
        body.agent, body.tool.name, body.tool.arguments, session_id=sid, **_ctx(body.context)
    )
    decision = get_security_engine().evaluate(event)
    get_session_registry().record(sid, decision.decision)
    return decision


@router.post("/proxy/output", response_model=AegisDecision)
def proxy_output(
    body: ProxyOutputRequest, _principal: str = Depends(require_gateway_access)
) -> AegisDecision:
    """Screen outbound text: strip injected instructions, redact secrets / PII."""
    sid = _session(body.agent, body.session_id)
    decision = get_security_engine().evaluate(
        AegisEvent.output(body.agent, body.text, session_id=sid)
    )
    get_session_registry().record(sid, decision.decision)
    return decision


@router.post("/proxy/chat", response_model=ProxyChatResponse)
def proxy_chat(
    body: ProxyChatRequest, request: Request, _principal: str = Depends(require_gateway_access)
) -> ProxyChatResponse:
    """A full guarded turn: screen input → forward to upstream → screen output."""
    engine = get_security_engine()
    sid = _session(body.agent, body.session_id)

    input_decisions = [
        engine.evaluate(AegisEvent.input(body.agent, m.content, session_id=sid))
        for m in body.messages
        if m.role == "user"
    ]
    blocked = first_block(input_decisions)
    if blocked is not None:
        get_session_registry().record(sid, Decision.BLOCK)
        return ProxyChatResponse(
            agent=body.agent,
            session_id=sid,
            decision=Decision.BLOCK,
            reason=blocked.reason,
            message=REFUSAL,
            input_decisions=input_decisions,
        )

    upstream: Upstream = _state(request, "proxy_upstream", None) or Upstream()
    completion = upstream.chat_completion(
        {"model": body.model, "messages": [m.model_dump() for m in body.messages], "_session": sid},
        agent=body.agent,
    )
    answer = completion["choices"][0]["message"].get("content") or ""

    out_decision = engine.evaluate(AegisEvent.output(body.agent, answer, session_id=sid))
    get_session_registry().record(sid, out_decision.decision)
    return ProxyChatResponse(
        agent=body.agent,
        session_id=sid,
        decision=out_decision.decision,
        reason=out_decision.reason,
        message=out_decision.sanitized_text if out_decision.sanitized_text is not None else answer,
        input_decisions=input_decisions,
        output_decision=out_decision,
        redactions=out_decision.redactions,
    )


@router.post("/proxy/mcp")
def proxy_mcp(
    body: dict,
    agent: str = Header(default=DEFAULT_AGENT, alias="X-Aegis-Agent"),
    _principal: str = Depends(require_gateway_access),
) -> dict:
    """Screen an MCP ``tools/call`` request before it reaches its MCP server."""
    adapter = get_adapter("mcp")
    sid = _session(agent, body.get("params", {}).get("_session"))
    events = adapter.normalize_tool_call(body, agent=agent, session_id=sid)
    decisions = [get_security_engine().evaluate(e) for e in events]
    for d in decisions:
        get_session_registry().record(sid, d.decision)
    return adapter.build_response(body, decisions)


# ------------------------------------------------ OpenAI-compatible endpoint
@router.post("/chat/completions")
def chat_completions(
    body: dict,
    request: Request,
    agent_header: str | None = Header(default=None, alias="X-Aegis-Agent"),
    session_header: str | None = Header(default=None, alias="X-Aegis-Session"),
    _principal: str = Depends(require_gateway_access),
) -> dict:
    """Drop-in OpenAI Chat Completions endpoint, guarded end to end.

    Point an existing agent's ``base_url`` here and nothing else changes: the
    request is screened, forwarded to the real model, and the model's proposed
    tool calls and final answer are screened on the way back.
    """
    adapter = OpenAIAdapter()
    engine = get_security_engine()
    agent = agent_header or _state(request, "proxy_agent", DEFAULT_AGENT)
    sid = _session(agent, session_header)
    model = body.get("model", "aegis")

    # 1. Screen every user message; a blocked one never reaches the model.
    input_decisions = [
        engine.evaluate(e)
        for e in adapter.normalize_input(body, agent=agent, session_id=sid)
    ]
    blocked = first_block(input_decisions)
    if blocked is not None:
        get_session_registry().record(sid, Decision.BLOCK)
        return adapter.refusal_response(model, REFUSAL)

    # 2. Forward to the real (OpenAI-compatible) upstream.
    upstream: Upstream = _state(request, "proxy_upstream", None) or Upstream()
    body["_session"] = sid
    completion = upstream.chat_completion(body, agent=agent)

    # 3. Screen the model's proposed tool calls and its final answer.
    tool_decisions = [
        engine.evaluate(e)
        for e in adapter.normalize_tool_call(completion, agent=agent, session_id=sid)
    ]
    out_decision = engine.evaluate(
        adapter.normalize_output(completion, agent=agent, session_id=sid)
    )
    for d in [*tool_decisions, out_decision]:
        get_session_registry().record(sid, d.decision)

    final = adapter.build_response(completion, [*tool_decisions, out_decision])
    final["aegis"] = {
        "session_id": sid,
        "input": [d.decision.value for d in input_decisions],
        "tools": [
            {"decision": d.decision.value, "reason_code": d.reason_code} for d in tool_decisions
        ],
        "output": out_decision.decision.value,
    }
    return final


def _ctx(context: dict) -> dict:
    """Pass through only the context keys the event model understands."""
    allowed = {"trust_score", "model"}
    return {k: v for k, v in context.items() if k in allowed}

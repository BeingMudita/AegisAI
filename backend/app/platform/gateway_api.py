"""The AegisAI security gateway — ``/v1/secure/*``.

An existing application routes its traffic through AegisAI instead of calling
its LLM/tools directly::

    Application → POST /v1/secure/chat → AegisAI → LLM / tools → guarded answer

The developer rebuilds nothing: they point at the gateway and get input
screening, trust verification, policy enforcement, tool authorization, DLP and
an audit trail for free.

Auth is deliberately zero-cost: send the shared ``X-Aegis-Key`` header (set
``AEGIS_API_KEY``), or a normal AegisAI JWT. When no key is configured the
gateway accepts a JWT and, outside production, is open so local integration is
friction-free.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.agents.runtime import get_runtime
from app.auth.security import decode_access_token
from app.auth.users import get_user
from app.config import get_settings
from app.database.enums import SubjectType
from app.firewall.scanner import get_firewall
from app.firewall.schemas import FirewallVerdict, ScanRequest
from app.platform.sdk import Decision, SecureResult
from app.policies.store import list_policies
from app.tools.gateway import get_tool_gateway
from app.tools.schemas import CheckResult
from app.trust.engine import get_trust_engine
from app.trust.scoring import level_for

router = APIRouter(prefix="/v1/secure", tags=["platform"])


# --------------------------------------------------------------------- auth
def _jwt_principal(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    data = decode_access_token(token)
    if data is None:
        return None
    user = get_user(data.username)
    if user is None or user.disabled:
        return None
    return user.username


def require_gateway_access(
    x_aegis_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> str:
    """Allow an API key, or a valid JWT, or (dev only, no key configured) anyone."""
    settings = get_settings()
    configured = settings.aegis_api_key
    if configured:
        if x_aegis_key and hmac.compare_digest(x_aegis_key.encode(), configured.encode()):
            return "api-key"
        principal = _jwt_principal(authorization)
        if principal:
            return principal
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Provide a valid X-Aegis-Key header or bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    principal = _jwt_principal(authorization)
    if principal:
        return principal
    if not settings.is_production:
        return "dev-open"
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="The gateway requires AEGIS_API_KEY to be set in production.",
    )


# ------------------------------------------------------------------ schemas
class ChatRequest(BaseModel):
    agent: str
    message: str = Field(min_length=1, max_length=8000)
    history: list[tuple[str, str]] = Field(default_factory=list)
    session_id: str | None = None


class ToolRequest(BaseModel):
    agent: str
    tool: str
    arguments: dict = Field(default_factory=dict)


class ToolCheckResponse(BaseModel):
    agent: str
    tool: str
    status: str
    decision: Decision
    reason: str
    checks: list[CheckResult]


class AgentAllowance(BaseModel):
    name: str
    trust_score: float
    trust_level: str
    allowed_tools: list[str]
    allowed_domains: list[str]
    sensitive_data: list[str]


# ---------------------------------------------------------------- endpoints
@router.post("/chat", response_model=SecureResult)
def secure_chat(
    body: ChatRequest, principal: str = Depends(require_gateway_access)
) -> SecureResult:
    """Run one guarded agent turn. Sync so FastAPI threadpools the LLM call.

    Trust signals are charged to the agent's score with the caller, so one
    integration's attacks never lower the agent's shared baseline."""
    turn = get_runtime().run_turn(
        agent=body.agent,
        session_id=body.session_id or "gateway",
        message=body.message,
        history=list(body.history),
        principal=principal,
    )
    return SecureResult.from_turn(turn)


@router.post("/tool", response_model=ToolCheckResponse)
def secure_tool(
    body: ToolRequest, _principal: str = Depends(require_gateway_access)
) -> ToolCheckResponse:
    """Pre-flight a tool call through the deny-by-default gateway (no execution)."""
    result = get_tool_gateway().authorize(body.agent, body.tool, body.arguments)
    status_value = result.status.value
    decision: Decision = (
        "BLOCK" if status_value == "DENIED" else "FLAG" if status_value == "PENDING" else "ALLOW"
    )
    return ToolCheckResponse(
        agent=body.agent,
        tool=body.tool,
        status=status_value,
        decision=decision,
        reason=result.decision_reason,
        checks=result.checks,
    )


@router.post("/scan", response_model=FirewallVerdict)
def secure_scan(
    body: ScanRequest, _principal: str = Depends(require_gateway_access)
) -> FirewallVerdict:
    """Screen a piece of text for prompt injection (input firewall as a service)."""
    return get_firewall().inspect(body.text, body.channel, context="gateway scan")


@router.get("/agents", response_model=list[AgentAllowance])
def secure_agents(_principal: str = Depends(require_gateway_access)) -> list[AgentAllowance]:
    """List the agents the gateway knows about and what each is allowed to do."""
    trust = get_trust_engine()
    out = []
    for policy in list_policies():
        score = trust.score(SubjectType.AGENT, policy.agent)
        out.append(
            AgentAllowance(
                name=policy.agent,
                trust_score=score,
                trust_level=level_for(score).value,
                allowed_tools=policy.allowed_tools,
                allowed_domains=policy.allowed_domains,
                sensitive_data=policy.sensitive_data,
            )
        )
    return out

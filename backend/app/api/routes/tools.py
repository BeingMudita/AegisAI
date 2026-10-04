"""Tools routes — the registry of permissioned agent tools and the gateway.

Staff can read the registry and the request log. Any principal may submit a
tool request on behalf of an agent; it passes the same gateway checks as a
request made from inside an agent turn.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import get_current_user, require_roles
from app.auth.roles import STAFF_ROLES
from app.auth.schemas import User
from app.tools.gateway import get_tool_gateway
from app.tools.schemas import ToolCallRequest, ToolCallResult

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("")
async def list_tools(
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict:
    """List registered tools with their risk level and trust requirement."""
    return {"tools": [t.model_dump(mode="json") for t in get_tool_gateway().describe()]}


@router.post("/execute", response_model=ToolCallResult)
def execute_tool(
    req: ToolCallRequest,
    user: User = Depends(get_current_user),
) -> ToolCallResult:
    """Ask the gateway to run a tool for an agent."""
    return get_tool_gateway().execute(req.agent, req.tool, req.arguments)


@router.get("/requests", response_model=list[ToolCallResult])
async def list_tool_requests(
    agent: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> list[ToolCallResult]:
    """The gateway's decision log, newest first."""
    return get_tool_gateway().requests(agent=agent, limit=limit)

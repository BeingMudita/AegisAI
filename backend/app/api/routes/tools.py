"""Tools routes — the registry of permissioned agent tools and the gateway.

Staff can read the registry and the request log. Calling a tool directly — outside
an agent turn — is an operator action and is ADMIN only: any other principal could
otherwise act *as* any agent (and earn trust on its behalf). Direct calls pass the
same gateway checks as calls made from inside an agent turn.

Handlers are plain ``def`` so FastAPI runs them in a worker thread: the stores
they reach may block on the database.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import require_roles
from app.auth.roles import STAFF_ROLES, Role
from app.auth.schemas import User
from app.tools.gateway import get_tool_gateway
from app.tools.schemas import ToolCallRequest, ToolCallResult

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("")
def list_tools(
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict:
    """List registered tools with their risk level and trust requirement."""
    return {"tools": [t.model_dump(mode="json") for t in get_tool_gateway().describe()]}


@router.post("/execute", response_model=ToolCallResult)
def execute_tool(
    req: ToolCallRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
) -> ToolCallResult:
    """Ask the gateway to run a tool for an agent (ADMIN only)."""
    return get_tool_gateway().execute(req.agent, req.tool, req.arguments)


@router.get("/requests", response_model=list[ToolCallResult])
def list_tool_requests(
    agent: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> list[ToolCallResult]:
    """The gateway's decision log, newest first."""
    return get_tool_gateway().requests(agent=agent, limit=limit)

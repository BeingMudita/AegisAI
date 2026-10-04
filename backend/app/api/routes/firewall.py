"""Firewall routes — scan text for prompt injection and inspect the rule set."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user, require_roles
from app.auth.roles import STAFF_ROLES
from app.auth.schemas import User
from app.firewall.scanner import get_firewall
from app.firewall.schemas import FirewallVerdict, RuleInfo, ScanRequest

router = APIRouter(prefix="/firewall", tags=["firewall"])


@router.post("/scan", response_model=FirewallVerdict)
def scan(
    req: ScanRequest,
    user: User = Depends(get_current_user),
) -> FirewallVerdict:
    """Scan text and return the firewall's verdict (the decision is audited)."""
    return get_firewall().inspect(req.text, req.channel, agent=user.username, context="api scan")


@router.get("/rules", response_model=list[RuleInfo])
def list_rules(
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> list[RuleInfo]:
    """List every detection rule and its weight."""
    return get_firewall().describe_rules()

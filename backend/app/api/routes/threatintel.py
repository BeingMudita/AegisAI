"""Threat intelligence routes — the shared, cross-agent threat feed.

Signatures are learned automatically as the security engine screens traffic; these
routes expose the feed and let a caller test content against the known signatures.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.auth.schemas import User
from app.platform.threatintel import ThreatMatch, ThreatSignature, get_threat_intel

router = APIRouter(prefix="/threat-intel", tags=["threat-intel"])


class MatchRequest(BaseModel):
    text: str


class MatchResponse(BaseModel):
    matched: bool
    match: ThreatMatch | None = None


@router.get("/signatures", response_model=list[ThreatSignature])
def signatures(limit: int = 100, user: User = Depends(get_current_user)) -> list[ThreatSignature]:
    """The platform-wide threat feed (newest first)."""
    return get_threat_intel().feed(limit=limit)


@router.post("/match", response_model=MatchResponse)
def match(body: MatchRequest, user: User = Depends(get_current_user)) -> MatchResponse:
    """Check a piece of content against the known attack signatures."""
    result = get_threat_intel().match(body.text)
    return MatchResponse(matched=result is not None, match=result)

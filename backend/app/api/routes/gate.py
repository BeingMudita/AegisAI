"""Security gate routes — audit + red-team + threshold → PASS / FAIL.

The same gate the CLI (`aegis gate`) and the GitHub Action use, exposed for the
dashboard and for programmatic CI integrations.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user
from app.auth.schemas import User
from app.platform import scanner
from app.platform.gate import GateResult, run_gate

router = APIRouter(prefix="/gate", tags=["gate"])


class GateRequest(BaseModel):
    target: str
    threshold: int = Field(default=90, ge=0, le=100)
    redteam: bool = True


@router.post("", response_model=GateResult)
def evaluate_gate(body: GateRequest, user: User = Depends(get_current_user)) -> GateResult:
    """Evaluate a target against the security gate (sync → threadpooled).

    Returns 200 with the full verdict whether it passed or failed; callers read
    ``passed`` to decide. A 404 means the target could not be resolved.
    """
    try:
        return run_gate(body.target, threshold=body.threshold, redteam=body.redteam)
    except scanner.ScannerError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

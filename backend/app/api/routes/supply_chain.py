"""Supply-chain routes: pinned models, their latest provenance checks, and the AI-BOM."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.auth.schemas import User
from app.supply_chain.aibom import build_aibom
from app.supply_chain.manifest import HuggingFacePin, OllamaPin, get_manifest
from app.supply_chain.provenance import ModelCheck, provenance_mode, recent_checks

router = APIRouter(prefix="/supply-chain", tags=["supply-chain"])


class SupplyChainReport(BaseModel):
    mode: str
    huggingface: list[HuggingFacePin]
    ollama: list[OllamaPin]
    checks: list[ModelCheck]


@router.get("", response_model=SupplyChainReport)
def report(user: User = Depends(get_current_user)) -> SupplyChainReport:
    """The model manifest and the outcome of every provenance check since start."""
    manifest = get_manifest()
    return SupplyChainReport(
        mode=provenance_mode(),
        huggingface=manifest.huggingface,
        ollama=manifest.ollama,
        checks=recent_checks(),
    )


@router.get("/aibom")
def aibom(user: User = Depends(get_current_user)) -> dict[str, Any]:
    """The pinned models as a CycloneDX 1.6 bill of materials."""
    return build_aibom(get_manifest())

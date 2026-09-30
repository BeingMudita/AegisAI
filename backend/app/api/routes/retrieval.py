"""Retrieval routes — RAG query interface over the pgvector knowledge base.

Phase 1 stubs; the actual retrieval pipeline lands with the RAG layer.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.auth.schemas import User

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.get("")
async def retrieval_status(user: User = Depends(get_current_user)) -> dict:
    """Report retrieval subsystem status (placeholder)."""
    return {"status": "not_implemented", "index_ready": False}

"""Retrieval routes — RAG search and question answering over pgvector."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.schemas import User
from app.database.session import get_db
from app.rag.embeddings import get_embedder
from app.rag.llm import OllamaClient
from app.rag.pipeline import answer_question
from app.rag.retrieval import retrieve
from app.rag.schemas import QueryRequest, RagAnswer, RetrievalResponse

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.get("")
async def retrieval_status(user: User = Depends(get_current_user)) -> dict:
    """Report retrieval subsystem status."""
    embedder = get_embedder()
    return {
        "status": "ready",
        "embedding_model": embedder.model_name,
        "embedding_dim": embedder.dim,
    }


@router.post("/search", response_model=RetrievalResponse)
async def search(
    req: QueryRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> RetrievalResponse:
    """Vector search: return the top-K chunks for a query."""
    results = await retrieve(session, req.query, top_k=req.top_k)
    return RetrievalResponse(query=req.query, top_k=len(results), results=results)


@router.post("/ask", response_model=RagAnswer)
async def ask(
    req: QueryRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> RagAnswer:
    """Full RAG: retrieve context, then answer with the LLM."""
    return await answer_question(session, req.query, top_k=req.top_k, llm=OllamaClient())

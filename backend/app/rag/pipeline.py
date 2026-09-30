"""Basic RAG pipeline: question + retrieved context → LLM → answer."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.llm import OllamaClient
from app.rag.retrieval import retrieve
from app.rag.schemas import RagAnswer, RetrievedChunk

SYSTEM_PROMPT = (
    "You are AegisAI, a helpful assistant that answers questions strictly from "
    "the provided context. If the answer is not in the context, say you don't "
    "know. Cite the source document titles you used."
)


def build_prompt(query: str, contexts: list[RetrievedChunk]) -> str:
    """Assemble the final prompt from the question and retrieved chunks."""
    if contexts:
        blocks = []
        for i, c in enumerate(contexts, start=1):
            label = c.document_title or c.source or c.document_id
            blocks.append(f"[Context {i} — {label}]\n{c.content}")
        context_text = "\n\n".join(blocks)
    else:
        context_text = "(no relevant context found)"

    return (
        f"Context:\n{context_text}\n\n"
        f"Question: {query}\n\n"
        f"Answer using only the context above:"
    )


async def answer_question(
    session: AsyncSession,
    query: str,
    *,
    top_k: int | None = None,
    llm: OllamaClient | None = None,
) -> RagAnswer:
    """Run retrieval + generation for a user question."""
    contexts = await retrieve(session, query, top_k=top_k)
    prompt = build_prompt(query, contexts)

    client = llm or OllamaClient()
    answer = await client.generate(prompt, system=SYSTEM_PROMPT)

    return RagAnswer(
        query=query,
        answer=answer,
        model=client.model,
        contexts=contexts,
    )

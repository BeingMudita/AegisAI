"""The document review queue: what the ingestion firewall found, for a person to sign off.

Screening already protects retrieval (blocked chunks are never indexed, flagged
ones are sanitized, untrusted sources are dropped at query time). Review adds
the human decision on top: keep the document (approve) or remove it. Approval
does not change what is indexed; it records who looked and when.
"""

from __future__ import annotations

import threading
import time

from app.firewall.schemas import FirewallAction
from app.rag.archive import chunk_view
from app.rag.knowledge_base import KnowledgeBase
from app.rag.schemas import (
    ArchiveChunk,
    DocumentReview,
    DocumentReviewPage,
    IngestReport,
    ReviewCounts,
    ReviewKind,
)

# Most urgent first.
_ORDER: dict[ReviewKind, int] = {"blocked": 0, "untrusted": 1, "sanitized": 2}
_COUNT_TTL = 10.0  # seconds the navigation badge's count may be reused


def review_kind(report: IngestReport, gate_reason: str | None) -> tuple[ReviewKind, str] | None:
    """Why a document needs a review, or ``None`` if screening found nothing."""
    if report.chunks_quarantined:
        n = report.chunks_quarantined
        return "blocked", (
            f"The ingestion firewall blocked {n} of {report.chunks_total} chunks; "
            "they are kept out of the index."
        )
    if gate_reason:
        return "untrusted", f"{gate_reason} Its chunks are left out of agent answers."
    if report.chunks_flagged:
        n = report.chunks_flagged
        return "sanitized", (
            f"{n} of {report.chunks_total} chunks held suspicious text that was removed "
            "before indexing."
        )
    return None


def _reviews(kb: KnowledgeBase) -> list[DocumentReview]:
    reports = kb.documents()
    gates = kb.source_gates(reports)
    items = []
    for r in reports:
        score, gate_reason = gates[r.document_id]
        found = review_kind(r, gate_reason)
        if found is None:
            continue
        kind, reason = found
        items.append(
            DocumentReview(
                **r.model_dump(),
                source_trust=score,
                retrieval_allowed=gate_reason is None,
                retrieval_reason=gate_reason,
                review_kind=kind,
                review_reason=reason,
                review_status="approved" if r.reviewed_at else "pending",
            )
        )
    return items


def _counts(items: list[DocumentReview]) -> ReviewCounts:
    pending = [i for i in items if i.review_status == "pending"]
    return ReviewCounts(
        blocked=sum(i.review_kind == "blocked" for i in pending),
        untrusted=sum(i.review_kind == "untrusted" for i in pending),
        sanitized=sum(i.review_kind == "sanitized" for i in pending),
        approved=len(items) - len(pending),
    )


def review_queue(
    kb: KnowledgeBase,
    *,
    kind: ReviewKind | None = None,
    status: str = "pending",
    query: str | None = None,
    offset: int = 0,
    limit: int = 25,
) -> DocumentReviewPage:
    """One page of the queue: most urgent first, newest first within a kind."""
    items = _reviews(kb)
    counts = _counts(items)
    needle = query.casefold() if query else None
    matches = [
        i
        for i in items
        if i.review_status == status
        and (kind is None or i.review_kind == kind)
        and (
            needle is None
            or any(
                needle in v.casefold()
                for v in (i.title, i.filename or "", i.source, i.section, i.folder)
            )
        )
    ]
    matches.sort(key=lambda i: i.created_at, reverse=True)
    matches.sort(key=lambda i: _ORDER[i.review_kind])
    return DocumentReviewPage(
        total=len(matches),
        offset=offset,
        limit=limit,
        items=matches[offset : offset + limit],
        counts=counts,
        has_more=offset + limit < len(matches),
    )


_cache_lock = threading.Lock()
_cached: tuple[float, int, int] | None = None  # (time, kb id, count)


def attention_count(kb: KnowledgeBase) -> int:
    """Pending blocked + untrusted documents, for the navigation badge (briefly cached)."""
    global _cached
    with _cache_lock:
        if _cached and _cached[1] == id(kb) and time.monotonic() - _cached[0] < _COUNT_TTL:
            return _cached[2]
    counts = _counts(_reviews(kb))
    value = counts.blocked + counts.untrusted
    with _cache_lock:
        _cached = (time.monotonic(), id(kb), value)
    return value


def forget_count() -> None:
    """Drop the cached badge count (after a decision, so the badge updates at once)."""
    global _cached
    with _cache_lock:
        _cached = None


def review_findings(
    kb: KnowledgeBase, document_id: str, limit: int = 20
) -> list[ArchiveChunk] | None:
    """The chunks behind a review: blocked and sanitized ones (or, for an
    untrusted source, the first few chunks), with their screening result."""
    report = kb.document(document_id)
    if report is None:
        return None
    _, gate_reason = kb.source_gate(report.source, report.trust_level)
    entries = kb.archive_entries(document_id, 0, max(1, report.chunks_total))
    notable = [e for e in entries if e["firewall_action"] != FirewallAction.ALLOW] or entries
    return [chunk_view(e, gate_reason) for e in notable[:limit]]

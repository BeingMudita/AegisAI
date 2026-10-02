"""The trust engine — tracks trust for agents, sources and tools, and gates
actions on it.

Scores live in an in-memory registry (the interim store, like the policy and
audit stores); every change is kept as a :class:`TrustAssessmentRecord`, the
shape of the ``trust_assessments`` table. A drop to a lower trust level raises
a ``TRUST_DEGRADATION`` security event.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache

from app.config import get_settings
from app.database.enums import (
    SecurityEventType,
    SecuritySeverity,
    SubjectType,
    TrustLevel,
)
from app.telemetry.store import get_audit_log
from app.trust.schemas import (
    TrustAssessmentRecord,
    TrustDecision,
    TrustScore,
    TrustScoreDetail,
)
from app.trust.scoring import (
    INITIAL_AGENT_TRUST,
    INITIAL_TOOL_TRUST,
    SOURCE_BASE_SCORE,
    SUSPENSION_THRESHOLD,
    TrustSignal,
    apply_signal,
    clamp,
    level_for,
)

_HISTORY_LEN = 200
_LEVEL_RANK = {lvl: i for i, lvl in enumerate(TrustLevel)}  # UNTRUSTED=0 … VERIFIED=4


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _Entry:
    subject_type: SubjectType
    subject_id: str
    score: float
    updated_at: datetime = field(default_factory=_now)
    count: int = 0
    history: deque[TrustAssessmentRecord] = field(
        default_factory=lambda: deque(maxlen=_HISTORY_LEN)
    )


class TrustEngine:
    """Thread-safe registry of trust scores with gating helpers."""

    def __init__(self, default_threshold: float = 0.6) -> None:
        self.default_threshold = default_threshold
        self._entries: dict[tuple[SubjectType, str], _Entry] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------ internals
    @staticmethod
    def _key(subject_type: SubjectType, subject_id: str) -> tuple[SubjectType, str]:
        return subject_type, subject_id.lower()

    def _entry(
        self, subject_type: SubjectType, subject_id: str, initial: float | None = None
    ) -> _Entry:
        key = self._key(subject_type, subject_id)
        entry = self._entries.get(key)
        if entry is None:
            if initial is None:
                initial = (
                    INITIAL_AGENT_TRUST if subject_type == SubjectType.AGENT else INITIAL_TOOL_TRUST
                )
            entry = _Entry(subject_type=subject_type, subject_id=subject_id, score=initial)
            self._entries[key] = entry
        return entry

    def _set(
        self,
        entry: _Entry,
        new_score: float,
        *,
        signal: str,
        rationale: str | None,
        assessed_by: str,
        session_id: str | None = None,
    ) -> TrustAssessmentRecord:
        previous = entry.score
        entry.score = round(clamp(new_score), 4)
        entry.updated_at = _now()
        entry.count += 1
        record = TrustAssessmentRecord(
            subject_type=entry.subject_type,
            subject_id=entry.subject_id,
            score=entry.score,
            previous=previous,
            level=level_for(entry.score),
            signal=signal,
            rationale=rationale,
            assessed_by=assessed_by,
        )
        entry.history.append(record)

        old_level, new_level = level_for(previous), record.level
        if _LEVEL_RANK[new_level] < _LEVEL_RANK[old_level]:
            get_audit_log().record_event(
                event_type=SecurityEventType.TRUST_DEGRADATION,
                severity=(
                    SecuritySeverity.HIGH
                    if new_level in {TrustLevel.LOW, TrustLevel.UNTRUSTED}
                    else SecuritySeverity.MEDIUM
                ),
                source="trust",
                agent=entry.subject_id if entry.subject_type == SubjectType.AGENT else None,
                session_id=session_id,
                description=(
                    f"{entry.subject_type.value} '{entry.subject_id}' trust fell "
                    f"{old_level.value} → {new_level.value} ({previous:.2f} → {entry.score:.2f})"
                ),
                details={"signal": signal, "rationale": rationale},
            )
        return record

    # -------------------------------------------------------------- reading
    def score(self, subject_type: SubjectType, subject_id: str) -> float:
        with self._lock:
            return self._entry(subject_type, subject_id).score

    def get(self, subject_type: SubjectType, subject_id: str) -> TrustScoreDetail | None:
        with self._lock:
            entry = self._entries.get(self._key(subject_type, subject_id))
            if entry is None:
                return None
            return TrustScoreDetail(
                **self._summary(entry).model_dump(),
                history=list(reversed(entry.history)),
            )

    def list_scores(self, subject_type: SubjectType | None = None) -> list[TrustScore]:
        with self._lock:
            entries = [
                e
                for e in self._entries.values()
                if subject_type is None or e.subject_type == subject_type
            ]
            return [self._summary(e) for e in sorted(entries, key=lambda e: e.score)]

    @staticmethod
    def _summary(entry: _Entry) -> TrustScore:
        return TrustScore(
            subject_type=entry.subject_type,
            subject_id=entry.subject_id,
            score=entry.score,
            level=level_for(entry.score),
            updated_at=entry.updated_at,
            assessments=entry.count,
        )

    # -------------------------------------------------------------- writing
    def register_source(self, name: str, declared: TrustLevel) -> float:
        """Ensure a document source exists, seeded from its declared trust level."""
        with self._lock:
            return self._entry(SubjectType.SOURCE, name, SOURCE_BASE_SCORE[declared]).score

    def observe(
        self,
        subject_type: SubjectType,
        subject_id: str,
        signal: TrustSignal,
        *,
        rationale: str | None = None,
        session_id: str | None = None,
    ) -> TrustAssessmentRecord:
        """Update a subject's score in response to an observed ``signal``."""
        with self._lock:
            entry = self._entry(subject_type, subject_id)
            return self._set(
                entry,
                apply_signal(entry.score, signal),
                signal=signal.value,
                rationale=rationale,
                assessed_by="trust-engine",
                session_id=session_id,
            )

    def override(
        self,
        subject_type: SubjectType,
        subject_id: str,
        score: float,
        *,
        rationale: str,
        assessed_by: str,
    ) -> TrustAssessmentRecord:
        """Set a score manually (admin action)."""
        with self._lock:
            entry = self._entry(subject_type, subject_id)
            return self._set(
                entry, score, signal="MANUAL_OVERRIDE", rationale=rationale, assessed_by=assessed_by
            )

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    # --------------------------------------------------------------- gating
    def evaluate(
        self,
        subject_type: SubjectType,
        subject_id: str,
        *,
        required: float | None = None,
        action: str = "act",
    ) -> TrustDecision:
        """Decide whether ``subject_id`` is trusted enough to perform ``action``."""
        need = self.default_threshold if required is None else required
        with self._lock:
            score = self._entry(subject_type, subject_id).score
        level = level_for(score)

        if subject_type == SubjectType.AGENT and score < SUSPENSION_THRESHOLD:
            allowed = False
            reason = f"'{subject_id}' is suspended: trust {score:.2f} < {SUSPENSION_THRESHOLD:.2f}."
        elif score >= need:
            allowed = True
            reason = f"Trust {score:.2f} meets the {need:.2f} required to {action}."
        else:
            allowed = False
            reason = f"Trust {score:.2f} is below the {need:.2f} required to {action}."

        get_audit_log().log_decision(
            "trust", allowed=allowed, subject=action, agent=subject_id, reason=reason
        )
        return TrustDecision(
            allowed=allowed,
            subject=subject_id,
            score=score,
            required=need,
            level=level,
            reason=reason,
        )


@lru_cache
def get_trust_engine() -> TrustEngine:
    """Return the process-wide trust engine."""
    return TrustEngine(default_threshold=get_settings().trust_threshold)

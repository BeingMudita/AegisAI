"""The trust engine — tracks trust for agents, sources and tools, and gates
actions on it.

Scores are held by a :class:`TrustRepository`: in memory by default, or in the
``trust_scores`` / ``trust_assessments`` tables with ``STORAGE_BACKEND=postgres``
(:class:`app.persistence.trust.PostgresTrustRepository`). Every change is an
atomic read-modify-write recorded as a :class:`TrustAssessmentRecord`; a drop to
a lower trust level raises a ``TRUST_DEGRADATION`` security event.

Agents are shared by every principal, so trust earned or lost while a principal
drives an agent is kept on a *scoped* subject, ``"<agent>@<principal>"``. A user's
attacks (or a conversation hijacked by injected content) degrade the agent for that
user only, and can't suspend it for everyone else. The agent's own score is the
baseline: administrators set it, and unattended runs (red-team, evaluation, direct
operator calls without a principal) move it. Every gate uses the lower of the two.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Protocol

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

HISTORY_LEN = 200
_LEVEL_RANK = {lvl: i for i, lvl in enumerate(TrustLevel)}  # UNTRUSTED=0 … VERIFIED=4
SCOPE_SEPARATOR = "@"

# compute(previous_score) -> new_score
Compute = Callable[[float], float]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def agent_subject(agent: str, principal: str | None = None) -> str:
    """The trust subject for ``agent`` acting for ``principal`` (the agent itself without one)."""
    return f"{agent}{SCOPE_SEPARATOR}{principal}" if principal else agent


def base_agent(subject_id: str) -> str:
    """The agent name of a (possibly scoped) agent subject."""
    return subject_id.split(SCOPE_SEPARATOR, 1)[0]


def default_initial(subject_type: SubjectType) -> float:
    return INITIAL_AGENT_TRUST if subject_type == SubjectType.AGENT else INITIAL_TOOL_TRUST


def make_record(
    subject_type: SubjectType,
    subject_id: str,
    previous: float,
    new_score: float,
    *,
    signal: str,
    rationale: str | None,
    assessed_by: str,
) -> TrustAssessmentRecord:
    return TrustAssessmentRecord(
        subject_type=subject_type,
        subject_id=subject_id,
        score=new_score,
        previous=previous,
        level=level_for(new_score),
        signal=signal,
        rationale=rationale,
        assessed_by=assessed_by,
        created_at=_now(),
    )


class TrustRepository(Protocol):
    """Where trust scores live. ``update`` must be atomic per subject."""

    def get_or_create(
        self, subject_type: SubjectType, subject_id: str, initial: float
    ) -> float: ...

    def peek(self, subject_type: SubjectType, subject_id: str) -> float | None:
        """The current score, or None if the subject has none (never creates one)."""
        ...

    def update(
        self,
        subject_type: SubjectType,
        subject_id: str,
        initial: float,
        compute: Compute,
        *,
        signal: str,
        rationale: str | None,
        assessed_by: str,
    ) -> TrustAssessmentRecord: ...

    def detail(self, subject_type: SubjectType, subject_id: str) -> TrustScoreDetail | None: ...

    def list(self, subject_type: SubjectType | None) -> list[TrustScore]: ...

    def clear(self) -> None: ...


# --------------------------------------------------------------------------- #
# In-memory repository
# --------------------------------------------------------------------------- #
@dataclass
class _Entry:
    subject_type: SubjectType
    subject_id: str
    score: float
    updated_at: datetime = field(default_factory=_now)
    count: int = 0
    history: deque[TrustAssessmentRecord] = field(default_factory=lambda: deque(maxlen=HISTORY_LEN))

    def summary(self) -> TrustScore:
        return TrustScore(
            subject_type=self.subject_type,
            subject_id=self.subject_id,
            score=self.score,
            level=level_for(self.score),
            updated_at=self.updated_at,
            assessments=self.count,
        )


class MemoryTrustRepository:
    def __init__(self) -> None:
        self._entries: dict[tuple[SubjectType, str], _Entry] = {}
        self._lock = threading.RLock()

    def _entry(self, subject_type: SubjectType, subject_id: str, initial: float) -> _Entry:
        key = (subject_type, subject_id.lower())
        entry = self._entries.get(key)
        if entry is None:
            entry = _Entry(subject_type=subject_type, subject_id=subject_id, score=initial)
            self._entries[key] = entry
        return entry

    def get_or_create(self, subject_type: SubjectType, subject_id: str, initial: float) -> float:
        with self._lock:
            return self._entry(subject_type, subject_id, initial).score

    def peek(self, subject_type: SubjectType, subject_id: str) -> float | None:
        with self._lock:
            entry = self._entries.get((subject_type, subject_id.lower()))
            return entry.score if entry else None

    def update(
        self,
        subject_type: SubjectType,
        subject_id: str,
        initial: float,
        compute: Compute,
        *,
        signal: str,
        rationale: str | None,
        assessed_by: str,
    ) -> TrustAssessmentRecord:
        with self._lock:
            entry = self._entry(subject_type, subject_id, initial)
            previous = entry.score
            entry.score = round(clamp(compute(previous)), 4)
            entry.updated_at = _now()
            entry.count += 1
            record = make_record(
                entry.subject_type, entry.subject_id, previous, entry.score,
                signal=signal, rationale=rationale, assessed_by=assessed_by,
            )  # fmt: skip
            entry.history.append(record)
            return record

    def detail(self, subject_type: SubjectType, subject_id: str) -> TrustScoreDetail | None:
        with self._lock:
            entry = self._entries.get((subject_type, subject_id.lower()))
            if entry is None:
                return None
            return TrustScoreDetail(
                **entry.summary().model_dump(), history=list(reversed(entry.history))
            )

    def list(self, subject_type: SubjectType | None) -> list[TrustScore]:
        with self._lock:
            entries = [
                e for e in self._entries.values()
                if subject_type is None or e.subject_type == subject_type
            ]  # fmt: skip
            return [e.summary() for e in sorted(entries, key=lambda e: e.score)]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
class TrustEngine:
    """Trust scores with gating helpers, over any :class:`TrustRepository`."""

    def __init__(
        self, default_threshold: float = 0.6, repository: TrustRepository | None = None
    ) -> None:
        self.default_threshold = default_threshold
        self.repo: TrustRepository = repository or MemoryTrustRepository()

    def _changed(
        self, record: TrustAssessmentRecord, session_id: str | None
    ) -> TrustAssessmentRecord:
        old_level, new_level = level_for(record.previous), record.level
        if _LEVEL_RANK[new_level] < _LEVEL_RANK[old_level]:
            get_audit_log().record_event(
                event_type=SecurityEventType.TRUST_DEGRADATION,
                severity=(
                    SecuritySeverity.HIGH
                    if new_level in {TrustLevel.LOW, TrustLevel.UNTRUSTED}
                    else SecuritySeverity.MEDIUM
                ),
                source="trust",
                agent=(
                    base_agent(record.subject_id)
                    if record.subject_type == SubjectType.AGENT
                    else None
                ),
                session_id=session_id,
                description=(
                    f"{record.subject_type.value} '{record.subject_id}' trust fell "
                    f"{old_level.value} → {new_level.value} "
                    f"({record.previous:.2f} → {record.score:.2f})"
                ),
                details={"signal": record.signal, "rationale": record.rationale},
            )
        return record

    # -------------------------------------------------------------- reading
    def score(self, subject_type: SubjectType, subject_id: str) -> float:
        return self.repo.get_or_create(subject_type, subject_id, default_initial(subject_type))

    def agent_score(self, agent: str, principal: str | None = None) -> float:
        """The trust that gates ``agent`` acting for ``principal``: the lower of the
        agent's baseline and its score with that principal."""
        baseline = self.score(SubjectType.AGENT, agent)
        if not principal:
            return baseline
        scoped = self.repo.peek(SubjectType.AGENT, agent_subject(agent, principal))
        return baseline if scoped is None else min(baseline, scoped)

    def get(self, subject_type: SubjectType, subject_id: str) -> TrustScoreDetail | None:
        return self.repo.detail(subject_type, subject_id)

    def list_scores(self, subject_type: SubjectType | None = None) -> list[TrustScore]:
        return self.repo.list(subject_type)

    # -------------------------------------------------------------- writing
    def register_source(self, name: str, declared: TrustLevel) -> float:
        """Ensure a document source exists, seeded from its declared trust level."""
        return self.repo.get_or_create(SubjectType.SOURCE, name, SOURCE_BASE_SCORE[declared])

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
        record = self.repo.update(
            subject_type,
            subject_id,
            default_initial(subject_type),
            lambda previous: apply_signal(previous, signal),
            signal=signal.value,
            rationale=rationale,
            assessed_by="trust-engine",
        )
        return self._changed(record, session_id)

    def observe_agent(
        self,
        agent: str,
        principal: str | None,
        signal: TrustSignal,
        *,
        rationale: str | None = None,
        session_id: str | None = None,
    ) -> TrustAssessmentRecord:
        """Record ``signal`` for ``agent`` — against its score with ``principal`` if
        there is one, so one principal's behaviour never moves the shared baseline."""
        return self.observe(
            SubjectType.AGENT,
            agent_subject(agent, principal),
            signal,
            rationale=rationale,
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
        record = self.repo.update(
            subject_type,
            subject_id,
            default_initial(subject_type),
            lambda _previous: score,
            signal="MANUAL_OVERRIDE",
            rationale=rationale,
            assessed_by=assessed_by,
        )
        return self._changed(record, None)

    def clear(self) -> None:
        self.repo.clear()

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
        return self._decide(
            subject_type,
            subject_id,
            self.score(subject_type, subject_id),
            required=required,
            action=action,
        )

    def evaluate_agent(
        self,
        agent: str,
        principal: str | None = None,
        *,
        required: float | None = None,
        action: str = "act",
    ) -> TrustDecision:
        """Gate ``agent`` acting for ``principal`` on :meth:`agent_score`."""
        name = f"{agent} (for {principal})" if principal else agent
        return self._decide(
            SubjectType.AGENT,
            name,
            self.agent_score(agent, principal),
            required=required,
            action=action,
        )

    def _decide(
        self,
        subject_type: SubjectType,
        subject_id: str,
        score: float,
        *,
        required: float | None,
        action: str,
    ) -> TrustDecision:
        need = self.default_threshold if required is None else required
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
    """Return the process-wide trust engine (durable in Postgres mode)."""
    settings = get_settings()
    repository: TrustRepository | None = None
    if settings.use_postgres:
        from app.persistence.trust import PostgresTrustRepository

        repository = PostgresTrustRepository()
    return TrustEngine(default_threshold=settings.trust_threshold, repository=repository)

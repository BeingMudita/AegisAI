"""The Aegis Threat Intelligence Engine — collective, cross-agent defence.

An agent learns from its own behaviour via the trust engine. Threat intelligence
lets every agent learn from the security events of the *whole platform*: when one
agent is attacked, AegisAI distils a normalized **threat signature** and shares it,
so another agent can be warned about a similar attack *before* it experiences it.

    Agent A ─▶ attack detected ─▶ threat signature ─┬─▶ Agent B  preemptive detection
                                                     └─▶ Agent C  preemptive detection

A signature is a fingerprint of the malicious content (shingles of its normalized
text) plus metadata (type, the tool/destination involved, severity). A new piece
of content is matched against the known signatures by token overlap (Jaccard), so
*variants* of a known attack are caught even when they fall below a single agent's
firewall threshold.

This adds no new detector — it records what the firewall already found and reuses
it across agents.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.firewall.normalize import normalize
from app.firewall.schemas import FirewallVerdict

_MATCH_THRESHOLD = 0.6  # Jaccard similarity to call it "the same attack"
_MAX_SIGNATURES = 500
_SHINGLE_K = 3
_WORD_RE = re.compile(r"[a-z0-9]+")

# Firewall categories → the normalized threat type reported to operators.
_TYPE_BY_CATEGORY: tuple[tuple[str, str], ...] = (
    ("DATA_EXFILTRATION", "DATA_EXFILTRATION"),
    ("INDIRECT_INJECTION", "INDIRECT_PROMPT_INJECTION"),
    ("PROMPT_EXFILTRATION", "PROMPT_INJECTION"),
    ("INSTRUCTION_OVERRIDE", "PROMPT_INJECTION"),
)


def _shingles(text: str) -> frozenset[str]:
    """k-word shingles of the normalized, lowercased text."""
    words = _WORD_RE.findall(normalize(text).text.lower())
    if len(words) < _SHINGLE_K:
        return frozenset(words)
    n = len(words) - _SHINGLE_K + 1
    return frozenset(" ".join(words[i : i + _SHINGLE_K]) for i in range(n))


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _classify(categories: list[str]) -> str:
    cats = {c.upper() for c in categories}
    for needle, label in _TYPE_BY_CATEGORY:
        if needle in cats:
            return label
    return "SUSPICIOUS_CONTENT"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ThreatSignature(BaseModel):
    """A normalized, shareable fingerprint of one observed attack."""

    id: str
    type: str
    severity: str  # HIGH | MEDIUM
    categories: list[str] = Field(default_factory=list)
    tool: str | None = None
    destination: str | None = None  # "external" | "internal" | a host
    excerpt: str = ""
    hits: int = 1
    agents: list[str] = Field(default_factory=list)
    first_seen: datetime = Field(default_factory=_now)
    last_seen: datetime = Field(default_factory=_now)
    # Not serialized to clients, used for matching.
    fingerprint: frozenset[str] = Field(default_factory=frozenset, exclude=True)

    model_config = {"arbitrary_types_allowed": True}


class ThreatMatch(BaseModel):
    """The result of matching content against the known signatures."""

    signature_id: str
    type: str
    severity: str
    similarity: float
    hits: int
    reason: str


class ThreatIntel:
    """A bounded, in-memory store of threat signatures with similarity matching."""

    def __init__(self) -> None:
        self._sigs: OrderedDict[str, ThreatSignature] = OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------- learning
    def record_text(
        self,
        text: str,
        categories: list[str],
        *,
        severity: str,
        agent: str | None = None,
        tool: str | None = None,
        destination: str | None = None,
    ) -> ThreatSignature | None:
        """Learn a signature from a piece of malicious content."""
        fingerprint = _shingles(text)
        if not fingerprint:
            return None
        threat_type = _classify(categories)
        sig_id = hashlib.sha1(
            (threat_type + "|" + "|".join(sorted(fingerprint)[:16])).encode()
        ).hexdigest()[:16]
        with self._lock:
            existing = self._sigs.get(sig_id)
            if existing is not None:
                existing.hits += 1
                existing.last_seen = _now()
                if agent and agent not in existing.agents:
                    existing.agents.append(agent)
                if severity == "HIGH":
                    existing.severity = "HIGH"
                self._sigs.move_to_end(sig_id)
                return existing
            sig = ThreatSignature(
                id=sig_id,
                type=threat_type,
                severity=severity,
                categories=sorted({c.upper() for c in categories}),
                tool=tool,
                destination=destination,
                excerpt=(text.strip()[:140]),
                agents=[agent] if agent else [],
                fingerprint=fingerprint,
            )
            self._sigs[sig_id] = sig
            while len(self._sigs) > _MAX_SIGNATURES:
                self._sigs.popitem(last=False)
            return sig

    def record_verdict(
        self, verdict: FirewallVerdict, text: str, *, agent: str | None = None
    ) -> ThreatSignature | None:
        """Learn from a firewall FLAG/BLOCK verdict (no-op for ALLOW)."""
        from app.firewall.schemas import FirewallAction

        if verdict.action == FirewallAction.ALLOW:
            return None
        severity = "HIGH" if verdict.action == FirewallAction.BLOCK else "MEDIUM"
        return self.record_text(text, verdict.categories, severity=severity, agent=agent)

    # ------------------------------------------------------------- matching
    def match(self, text: str) -> ThreatMatch | None:
        """Return the best known signature similar to ``text``, if any."""
        fingerprint = _shingles(text)
        if not fingerprint:
            return None
        best: tuple[float, ThreatSignature] | None = None
        with self._lock:
            for sig in self._sigs.values():
                score = _jaccard(fingerprint, sig.fingerprint)
                if score >= _MATCH_THRESHOLD and (best is None or score > best[0]):
                    best = (score, sig)
        if best is None:
            return None
        score, sig = best
        return ThreatMatch(
            signature_id=sig.id,
            type=sig.type,
            severity=sig.severity,
            similarity=round(score, 3),
            hits=sig.hits,
            reason=(
                f"Matches known attack '{sig.type}' (signature {sig.id}, seen {sig.hits}×) "
                f"at {score:.0%} similarity."
            ),
        )

    # --------------------------------------------------------------- feed
    def feed(self, *, limit: int = 100) -> list[ThreatSignature]:
        with self._lock:
            return [s.model_copy() for s in reversed(self._sigs.values())][:limit]

    def get(self, signature_id: str) -> ThreatSignature | None:
        with self._lock:
            return self._sigs.get(signature_id)

    def clear(self) -> None:
        with self._lock:
            self._sigs.clear()


_intel = ThreatIntel()


def get_threat_intel() -> ThreatIntel:
    """Return the process-wide threat intelligence store."""
    return _intel

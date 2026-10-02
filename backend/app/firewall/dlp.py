"""Data-loss prevention — redact secrets and personal data from outbound text.

Secrets (API keys, tokens, inline passwords) are always redacted. Personal
data (emails, phone numbers, card numbers, SSNs) is redacted when the agent's
policy marks the data it touched as sensitive.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field


def _luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("API_KEY", re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{20,}\b")),
    ("API_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("API_KEY", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}\b")),
    ("TOKEN", re.compile(r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}\b")),
    (
        "PRIVATE_KEY",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    ),
    (
        "CREDENTIAL",
        re.compile(r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|token)\s*[:=]\s*[^\s,;]+"),
    ),
)

_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    # International (+CC then 2–4 digit groups) first, then North-American style
    ("PHONE", re.compile(r"(?<!\w)\+\d{1,3}(?:[\s.-]?\(?\d{1,4}\)?){2,4}\b")),
    ("PHONE", re.compile(r"(?<![\w+])\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")),
)
_CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")


@dataclass
class DlpResult:
    text: str
    redactions: Counter[str] = field(default_factory=Counter)

    @property
    def redacted(self) -> bool:
        return bool(self.redactions)


def redact(text: str, *, pii: bool = True) -> DlpResult:
    """Mask secrets (always) and personal data (when ``pii``) in ``text``."""
    counts: Counter[str] = Counter()

    def _sub(label: str, pattern: re.Pattern[str], s: str) -> str:
        def repl(_: re.Match[str]) -> str:
            counts[label] += 1
            return f"[{label} REDACTED]"

        return pattern.sub(repl, s)

    for label, pattern in _SECRET_PATTERNS:
        text = _sub(label, pattern, text)

    if pii:

        def card_repl(m: re.Match[str]) -> str:
            digits = re.sub(r"\D", "", m.group(0))
            if 13 <= len(digits) <= 19 and _luhn_ok(digits):
                counts["CARD"] += 1
                return "[CARD REDACTED]"
            return m.group(0)

        text = _CARD.sub(card_repl, text)
        for label, pattern in _PII_PATTERNS:
            text = _sub(label, pattern, text)

    return DlpResult(text=text, redactions=counts)

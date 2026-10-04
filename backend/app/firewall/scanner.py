"""The prompt-injection firewall.

``scan`` is pure (no I/O) so it can be benchmarked and unit-tested directly;
``inspect`` wraps it with audit logging and is what the rest of the system
calls at each checkpoint (user input, retrieved chunks, tool arguments, tool
output).

Scoring: every rule that fires contributes its weight ``w``; weights combine
with a noisy-OR, ``score = 1 - Π(1 - w)``, so one strong signal is enough to
block while several weak ones accumulate.
"""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.database.enums import SecurityEventType, SecuritySeverity
from app.firewall.normalize import normalize, strip_invisible
from app.firewall.rules import RULES, SIGNAL_RULES, Rule
from app.firewall.schemas import (
    ContentChannel,
    FirewallAction,
    FirewallVerdict,
    RuleInfo,
    RuleMatch,
)
from app.telemetry.store import get_audit_log

_EXCERPT_LEN = 80
REDACTION = "[REMOVED: suspected injection]"


def _excerpt(text: str) -> str:
    text = text.strip()
    return text if len(text) <= _EXCERPT_LEN else text[: _EXCERPT_LEN - 1] + "…"


class PromptFirewall:
    """Scores text for injection risk and decides ALLOW / FLAG / BLOCK."""

    def __init__(
        self,
        block_threshold: float = 0.8,
        flag_threshold: float = 0.4,
        rules: tuple[Rule, ...] = RULES,
    ) -> None:
        if not 0 < flag_threshold <= block_threshold <= 1:
            raise ValueError("Require 0 < flag_threshold <= block_threshold <= 1.")
        self.block_threshold = block_threshold
        self.flag_threshold = flag_threshold
        self.rules = rules

    # ------------------------------------------------------------- scanning
    def scan(
        self, text: str, channel: ContentChannel = ContentChannel.USER_INPUT
    ) -> FirewallVerdict:
        """Evaluate ``text`` and return a verdict. Pure — records nothing."""
        norm = normalize(text)
        indirect = channel.is_indirect
        matches: dict[str, RuleMatch] = {}

        # 1. Canonical text — spans are recorded so the match can be redacted.
        for rule in self.rules:
            m = rule.pattern.search(norm.text)
            if m:
                matches[rule.rule_id] = RuleMatch(
                    rule_id=rule.rule_id,
                    category=rule.category,
                    weight=rule.weight_for(indirect),
                    excerpt=_excerpt(m.group(0)),
                    start=m.start(),
                    end=m.end(),
                )

        # 2. Alternate readings (de-leeted, de-spaced). A rule that only fires
        #    here means the author obfuscated it on purpose. Spans are mapped back
        #    to the canonical text so the obfuscated span can be redacted too.
        evaded = False
        for number, variant in enumerate(norm.variants):
            for rule in self.rules:
                if rule.rule_id in matches:
                    continue
                m = rule.pattern.search(variant)
                if m:
                    evaded = True
                    start, end = norm.variant_span(number, m.start(), m.end())
                    matches[rule.rule_id] = RuleMatch(
                        rule_id=rule.rule_id,
                        category=rule.category,
                        weight=rule.weight_for(indirect),
                        excerpt=_excerpt(m.group(0)),
                        start=start,
                        end=end,
                    )

        # 3. Encoded payloads — the span is the whole encoded token.
        hidden_payload = False
        for payload, (start, end) in zip(norm.decoded_payloads, norm.payload_spans, strict=True):
            for rule in self.rules:
                m = rule.pattern.search(payload)
                if m and rule.rule_id not in matches:
                    hidden_payload = True
                    matches[rule.rule_id] = RuleMatch(
                        rule_id=rule.rule_id,
                        category=rule.category,
                        weight=rule.weight_for(indirect),
                        excerpt=_excerpt("base64→ " + m.group(0)),
                        start=start,
                        end=end,
                    )

        # 4. Obfuscation signals.
        if norm.invisible_count:
            self._add_signal(
                matches, "OB-001", f"{norm.invisible_count} invisible char(s)", indirect
            )
        if norm.homoglyph_count:
            self._add_signal(
                matches, "OB-002", f"{norm.homoglyph_count} mixed-script word(s)", indirect
            )
        if evaded and norm.spaced_letter_runs:
            self._add_signal(matches, "OB-003", "spaced-out letters", indirect)
        if hidden_payload:
            self._add_signal(matches, "OB-004", "base64-encoded instructions", indirect)

        return self._verdict(list(matches.values()), channel)

    @staticmethod
    def _add_signal(
        matches: dict[str, RuleMatch], rule_id: str, excerpt: str, indirect: bool
    ) -> None:
        category, weight, _ = SIGNAL_RULES[rule_id]
        if indirect:
            weight = min(0.99, weight * 1.15)
        matches[rule_id] = RuleMatch(
            rule_id=rule_id, category=category, weight=weight, excerpt=excerpt
        )

    def _verdict(self, matches: list[RuleMatch], channel: ContentChannel) -> FirewallVerdict:
        clean = 1.0
        for match in matches:
            clean *= 1.0 - match.weight
        score = round(1.0 - clean, 4)

        if score >= self.block_threshold:
            action = FirewallAction.BLOCK
        elif score >= self.flag_threshold:
            action = FirewallAction.FLAG
        else:
            action = FirewallAction.ALLOW

        categories = sorted({m.category for m in matches})
        if not matches:
            reason = "No injection signals detected."
        else:
            reason = (
                f"{action.value}: score {score:.2f} from {len(matches)} signal(s) "
                f"[{', '.join(categories)}]."
            )
        return FirewallVerdict(
            action=action,
            score=score,
            channel=channel,
            matches=sorted(matches, key=lambda m: m.weight, reverse=True),
            categories=categories,
            reason=reason,
        )

    # ------------------------------------------------------------ sanitizing
    @staticmethod
    def sanitize(text: str, verdict: FirewallVerdict) -> str:
        """Return ``text`` with every matched injection span replaced by a marker.

        Spans are found in the canonical text and cut out of the *original*, so the
        rest keeps its line breaks, tables and non-Latin script; invisible characters
        are stripped from what is kept. ``verdict`` must come from scanning ``text``.
        """
        norm = normalize(text)
        merged: list[list[int]] = []
        for start, end in sorted((m.start, m.end) for m in verdict.matches if m.start >= 0):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        out: list[str] = []
        kept_from = 0
        for start, end in merged:
            cut_start, cut_end = norm.original_span(start, end)
            out.append(strip_invisible(text[kept_from:cut_start]))
            out.append(REDACTION)
            kept_from = cut_end
        out.append(strip_invisible(text[kept_from:]))
        return "".join(out)

    # ------------------------------------------------------------- auditing
    def inspect(
        self,
        text: str,
        channel: ContentChannel = ContentChannel.USER_INPUT,
        *,
        agent: str | None = None,
        session_id: str | None = None,
        context: str | None = None,
    ) -> FirewallVerdict:
        """Scan ``text`` and record the decision in the audit log."""
        verdict = self.scan(text, channel)
        get_audit_log().log_decision(
            "firewall",
            allowed=verdict.allowed,
            subject=channel.value,
            agent=agent,
            reason=verdict.reason,
        )
        self.record_incident(verdict, agent=agent, session_id=session_id, context=context)
        return verdict

    @staticmethod
    def record_incident(
        verdict: FirewallVerdict,
        *,
        agent: str | None = None,
        session_id: str | None = None,
        context: str | None = None,
    ) -> None:
        """Record a security event for a FLAG / BLOCK verdict (no-op for ALLOW).

        Bulk callers (document ingestion) use ``scan`` + this, and count their
        decisions in aggregate instead of logging one line per chunk.
        """
        audit = get_audit_log()
        channel = verdict.channel
        if verdict.action != FirewallAction.ALLOW:
            if verdict.action == FirewallAction.BLOCK:
                severity = (
                    SecuritySeverity.CRITICAL if verdict.score >= 0.95 else SecuritySeverity.HIGH
                )
            else:
                severity = SecuritySeverity.MEDIUM
            audit.record_event(
                event_type=SecurityEventType.PROMPT_INJECTION,
                severity=severity,
                source="firewall",
                agent=agent,
                session_id=session_id,
                description=f"{verdict.action.value} on {channel.value}"
                + (f" ({context})" if context else "")
                + f": {', '.join(verdict.categories)}",
                details={
                    "score": verdict.score,
                    "channel": channel.value,
                    "rules": [m.rule_id for m in verdict.matches],
                    "excerpt": verdict.matches[0].excerpt if verdict.matches else None,
                },
            )

    def describe_rules(self) -> list[RuleInfo]:
        """List every rule the firewall applies."""
        infos = [
            RuleInfo(
                rule_id=r.rule_id, category=r.category, weight=r.weight, description=r.description
            )
            for r in self.rules
        ]
        infos += [
            RuleInfo(rule_id=rid, category=cat, weight=w, description=desc)
            for rid, (cat, w, desc) in SIGNAL_RULES.items()
        ]
        return infos


@lru_cache
def get_firewall() -> PromptFirewall:
    """Return the process-wide firewall configured from settings."""
    settings = get_settings()
    return PromptFirewall(
        block_threshold=settings.firewall_block_threshold,
        flag_threshold=settings.firewall_flag_threshold,
    )

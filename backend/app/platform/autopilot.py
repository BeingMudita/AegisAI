"""Aegis Autopilot — continuously improve a policy from runtime behaviour.

The scanner generates a policy once, from an agent's declared shape. Autopilot
watches what the agent actually *does* at runtime (the tool-gateway request log)
and proposes tightening changes — but never silently edits a production policy.
Each proposal is a recommendation a human can **Apply**, **Reject** or
**Simulate**::

    runtime logs → risk analysis → policy weakness → recommendation → (human) → apply → red-team

Everything is derived from the real request log and the live policy; applying a
recommendation goes through the same policy-as-code path as ``aegis.yaml``.
"""

from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel, Field

from app.policies.config import ToolPolicy, get_global_config, register_tool_policy
from app.policies.schemas import AgentPolicy
from app.policies.store import get_policy, register_policy
from app.tools.gateway import get_tool_gateway

_INTERNAL_DOMAIN = "company.com"


class PolicyRecommendation(BaseModel):
    """A single proposed policy change, with the actions a human can take."""

    id: str  # stable, derived (kind:subject) so it can be applied without server state
    agent: str
    kind: str  # restrict_domain | remove_unused_tool | require_approval
    risk: str  # HIGH | MEDIUM | LOW
    observed: str
    change_summary: str
    suggested_yaml: str
    actions: list[str] = Field(default_factory=lambda: ["Apply", "Reject", "Simulate"])


class SimulationResult(BaseModel):
    recommendation: str
    score_before: int
    score_after: int
    delta: int
    note: str


class AutopilotError(ValueError):
    """The recommendation could not be found or applied."""


def _host(value: str) -> str:
    value = value.strip()
    if "@" in value and "://" not in value:
        return value.rsplit("@", 1)[-1].lower()
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return (parsed.hostname or "").lower()


def _external_arg(tool: str) -> str | None:
    info = next((t for t in get_tool_gateway().describe() if t.name == tool), None)
    return info.domain_checked_argument if info else None


def _high_impact(tool: str) -> bool:
    info = next((t for t in get_tool_gateway().describe() if t.name == tool), None)
    if info is None:
        return False
    return info.risk_level.value in {"HIGH", "CRITICAL"} or bool(info.domain_checked_argument)


def analyze(agent: str) -> list[PolicyRecommendation]:
    """Derive tightening recommendations from the agent's runtime behaviour."""
    policy = get_policy(agent)
    if policy is None:
        raise AutopilotError(f"No policy exists for agent '{agent}'.")
    calls = get_tool_gateway().requests(agent=agent, limit=1000)
    # The proxy authorizes tool calls as a dry run (not persisted to the request
    # log), so also mine what the adaptive monitor observed at runtime.
    from app.platform.adaptive import get_adaptive_monitor

    observed = get_adaptive_monitor().recent_events(agent)
    recs: list[PolicyRecommendation] = []

    # 1. A wildcard / empty domain allow-list while external tools are permitted.
    external_tools = [t for t in policy.allowed_tools if _external_arg(t)]
    if external_tools and ("*" in policy.allowed_domains or not policy.allowed_domains):
        recs.append(
            PolicyRecommendation(
                id="restrict_domain:*",
                agent=agent,
                kind="restrict_domain",
                risk="HIGH",
                observed=(
                    "External-capable tools "
                    f"({', '.join(external_tools)}) with an unrestricted domain allow-list."
                ),
                change_summary=f"Restrict external destinations to {_INTERNAL_DOMAIN}.",
                suggested_yaml=f"domains:\n  allowed:\n    - {_INTERNAL_DOMAIN}",
            )
        )

    # 2. Observed attempts to reach destinations outside the allow-list.
    allowed = {d.lower() for d in policy.allowed_domains}
    offenders: dict[str, set[str]] = {}
    seen: list[tuple[str, str]] = [  # (tool, host) from both sources
        (c.tool, _host(str(c.arguments.get(_external_arg(c.tool) or "", ""))))
        for c in calls
        if _external_arg(c.tool)
    ] + [(e.tool, e.host or "") for e in observed if e.external]
    for tool, host in seen:
        if host and "*" not in allowed and host not in allowed:
            offenders.setdefault(tool, set()).add(host)
    for tool, hosts in offenders.items():
        recs.append(
            PolicyRecommendation(
                id=f"restrict_domain:{tool}",
                agent=agent,
                kind="restrict_domain",
                risk="MEDIUM",
                observed=(
                    f"{tool} was called with off-list destination(s): "
                    f"{', '.join(sorted(hosts))}."
                ),
                change_summary=f"Keep {tool} restricted to the allow-list ({_INTERNAL_DOMAIN}).",
                suggested_yaml=f"domains:\n  allowed:\n    - {_INTERNAL_DOMAIN}",
            )
        )

    # 3. Tools granted but never used — least privilege says drop them.
    used = {c.tool for c in calls} | {e.tool for e in observed}
    if used:
        for tool in policy.allowed_tools:
            if tool not in used:
                recs.append(
                    PolicyRecommendation(
                        id=f"remove_unused_tool:{tool}",
                        agent=agent,
                        kind="remove_unused_tool",
                        risk="LOW",
                        observed=f"'{tool}' is permitted but was never called in the window.",
                        change_summary=f"Remove '{tool}' from permissions (deny by default).",
                        suggested_yaml=f"permissions:\n  tools:  # remove\n    - {tool}",
                    )
                )

    # 4. High-impact tools used without human approval.
    config = get_global_config()
    for tool in sorted(used):
        if tool not in policy.allowed_tools or not _high_impact(tool):
            continue
        tp = config.tool(tool)
        if tp and not tp.requires_approval:
            recs.append(
                PolicyRecommendation(
                    id=f"require_approval:{tool}",
                    agent=agent,
                    kind="require_approval",
                    risk="HIGH",
                    observed=f"High-impact tool '{tool}' ran without human approval.",
                    change_summary=f"Require approval for '{tool}'.",
                    suggested_yaml=f"approval:\n  required_for:\n    - {tool}",
                )
            )
    return recs


def _find(agent: str, recommendation_id: str) -> PolicyRecommendation:
    rec = next((r for r in analyze(agent) if r.id == recommendation_id), None)
    if rec is None:
        raise AutopilotError(f"No current recommendation '{recommendation_id}' for '{agent}'.")
    return rec


def _apply_to_policy(policy: AgentPolicy, rec: PolicyRecommendation) -> AgentPolicy:
    """Return a copy of ``policy`` with the recommendation applied."""
    updated = policy.model_copy(deep=True)
    if rec.kind == "restrict_domain":
        updated.allowed_domains = [_INTERNAL_DOMAIN]
    elif rec.kind == "remove_unused_tool":
        tool = rec.id.split(":", 1)[1]
        updated.allowed_tools = [t for t in updated.allowed_tools if t != tool]
    return updated


def apply(agent: str, recommendation_id: str) -> PolicyRecommendation:
    """Apply a recommendation to the live policy (a human-confirmed action)."""
    rec = _find(agent, recommendation_id)
    policy = get_policy(agent)
    if policy is None:
        raise AutopilotError(f"No policy exists for agent '{agent}'.")
    if rec.kind == "require_approval":
        tool = rec.id.split(":", 1)[1]
        base = get_global_config().tool(tool) or ToolPolicy(name=tool)
        tp = base.model_copy(deep=True)
        tp.requires_approval = True
        register_tool_policy(tp)
    else:
        register_policy(_apply_to_policy(policy, rec))
    return rec


def simulate(agent: str, recommendation_id: str) -> SimulationResult:
    """Score the agent before and after the change, without keeping it."""
    from app.platform import scanner

    rec = _find(agent, recommendation_id)
    policy = get_policy(agent)
    if policy is None:
        raise AutopilotError(f"No policy exists for agent '{agent}'.")

    before = scanner.score_report(scanner.profile_known_agent(agent)).score
    original = policy.model_copy(deep=True)
    try:
        register_policy(_apply_to_policy(policy, rec))
        after = scanner.score_report(scanner.profile_known_agent(agent)).score
    finally:
        register_policy(original)  # restore — simulation never persists
    return SimulationResult(
        recommendation=rec.id,
        score_before=before,
        score_after=after,
        delta=after - before,
        note=f"Applying '{rec.id}' would move the security score {before} → {after}.",
    )

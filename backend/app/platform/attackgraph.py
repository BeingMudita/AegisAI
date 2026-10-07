"""Attack-surface graph, attack-path analysis, blast radius and risk-guided red teaming.

Individual checks ask *"is this one tool / domain / data category allowed?"* This
module asks the harder, more interesting question: *"what do an agent's
permissions allow when you **compose** them?"*

It builds an attack-surface graph from the agent's profile (tools, data sources,
destinations, sensitive data), enumerates dangerous **paths** through it (e.g.
``RAG → agent → read_database → send_email → external``), scores the agent's
**blast radius** if it were compromised, and uses the most dangerous path to
focus the red team — risk-guided rather than random.

Everything is derived from the scanner's :class:`AgentProfile`, so it composes
with ``aegis audit`` / ``generate-policy`` and gives the policy generator a
measurable objective: shrink the blast radius.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.platform.scanner import AgentProfile, ToolProfile, profile_target

_TOOL_WEIGHT = {"CRITICAL": 15, "HIGH": 10, "MEDIUM": 5, "LOW": 2}


class GraphNode(BaseModel):
    id: str
    label: str
    kind: str  # agent | tool | data | destination | source


class GraphEdge(BaseModel):
    source: str
    target: str
    label: str = ""


class AttackSurfaceGraph(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class AttackPath(BaseModel):
    kind: str  # data_exfiltration | indirect_injection_to_exfil | privilege_escalation
    risk: str  # HIGH | MEDIUM | LOW
    steps: list[str]
    detail: str


class BlastComponent(BaseModel):
    name: str
    severity: str  # CRITICAL | HIGH | MEDIUM | LOW


class BlastRadius(BaseModel):
    score: int  # 0–100, higher = worse
    level: str  # red | orange | green
    accessible_data: list[str] = Field(default_factory=list)
    destinations: list[str] = Field(default_factory=list)
    dangerous_actions: list[str] = Field(default_factory=list)
    components: list[BlastComponent] = Field(default_factory=list)
    paths: int = 0
    breakdown: dict[str, int] = Field(default_factory=dict)


class RiskFocus(BaseModel):
    family: str
    priority: int  # 1 = highest
    rationale: str


class AttackSurfaceReport(BaseModel):
    agent: str
    graph: AttackSurfaceGraph
    paths: list[AttackPath]
    blast_radius: BlastRadius
    risk_guided: list[RiskFocus]


# --------------------------------------------------------------------- helpers
def _domains_locked(profile: AgentProfile) -> bool:
    return bool(profile.allowed_domains) and "*" not in profile.allowed_domains


def _sensitive_categories(profile: AgentProfile) -> list[str]:
    cats = {t.data_category for t in profile.allowed_tool_profiles if t.data_category}
    cats.update(profile.sensitive_data)
    return sorted(c for c in cats if c)


def _destination_label(profile: AgentProfile) -> str:
    if _domains_locked(profile):
        return ", ".join(profile.allowed_domains)
    return "ANY external host"


# ------------------------------------------------------------------- the graph
def build_graph(profile: AgentProfile) -> AttackSurfaceGraph:
    nodes: list[GraphNode] = [GraphNode(id="agent", label=profile.name, kind="agent")]
    edges: list[GraphEdge] = []
    seen: set[str] = {"agent"}

    def _add(node: GraphNode) -> None:
        if node.id not in seen:
            nodes.append(node)
            seen.add(node.id)

    for source in profile.data_sources:
        sid = f"source:{source.name}"
        _add(GraphNode(id=sid, label=source.name, kind="source"))
        edges.append(
            GraphEdge(
                source=sid, target="agent", label="untrusted" if source.untrusted else "feeds"
            )
        )

    dest_label = _destination_label(profile)
    for tool in profile.allowed_tool_profiles:
        tid = f"tool:{tool.name}"
        _add(GraphNode(id=tid, label=tool.name, kind="tool"))
        edges.append(GraphEdge(source="agent", target=tid, label=tool.risk_level))
        if tool.data_category:
            did = f"data:{tool.data_category}"
            _add(GraphNode(id=did, label=tool.data_category, kind="data"))
            edges.append(GraphEdge(source=tid, target=did, label="reads"))
        if tool.external:
            dest_id = f"dest:{dest_label}"
            _add(GraphNode(id=dest_id, label=dest_label, kind="destination"))
            edges.append(GraphEdge(source=tid, target=dest_id, label=tool.domain_kind or "url"))
    return AttackSurfaceGraph(nodes=nodes, edges=edges)


# --------------------------------------------------------------- attack paths
def attack_paths(profile: AgentProfile) -> list[AttackPath]:
    allowed = profile.allowed_tool_profiles
    external = [t for t in allowed if t.external]
    sensitive_tools = [t for t in allowed if t.data_category]
    sens_cats = _sensitive_categories(profile)
    locked = _domains_locked(profile)
    untrusted = [d for d in profile.data_sources if d.untrusted]
    paths: list[AttackPath] = []

    if external and (sensitive_tools or sens_cats):
        reader = sensitive_tools[0].name if sensitive_tools else "read_database"
        sender = external[0].name
        risk = "HIGH" if not locked else "MEDIUM"
        paths.append(
            AttackPath(
                kind="data_exfiltration",
                risk=risk,
                steps=[profile.name, reader, sender, _destination_label(profile)],
                detail=(
                    f"{', '.join(sens_cats) or 'sensitive data'} can be read via {reader} and "
                    f"sent out via {sender} to {_destination_label(profile)}."
                    + ("" if locked else " No domain allow-list constrains the destination.")
                ),
            )
        )

    if untrusted and external and (sensitive_tools or sens_cats):
        paths.append(
            AttackPath(
                kind="indirect_injection_to_exfil",
                risk="HIGH",
                steps=[
                    untrusted[0].name,
                    profile.name,
                    (sensitive_tools[0].name if sensitive_tools else "read_database"),
                    external[0].name,
                    _destination_label(profile),
                ],
                detail=(
                    f"An injection in '{untrusted[0].name}' could drive the agent to read "
                    f"sensitive data and exfiltrate it via {external[0].name}."
                ),
            )
        )

    gap = [t for t in allowed if t.high_impact and not t.requires_approval]
    if gap:
        paths.append(
            AttackPath(
                kind="privilege_escalation",
                risk="MEDIUM",
                steps=[profile.name, *(t.name for t in gap)],
                detail=(
                    "High-impact tool(s) run without human approval: "
                    + ", ".join(t.name for t in gap)
                    + "."
                ),
            )
        )
    return paths


# -------------------------------------------------------------- blast radius
def _severity(tool: ToolProfile) -> str:
    return tool.risk_level


def blast_radius(profile: AgentProfile) -> BlastRadius:
    allowed = profile.allowed_tool_profiles
    external = [t for t in allowed if t.external]
    locked = _domains_locked(profile)
    sens_cats = _sensitive_categories(profile)
    no_approval = [t for t in allowed if t.high_impact and not t.requires_approval]
    paths = [p for p in attack_paths(profile) if p.risk == "HIGH"]

    breakdown = {
        "tools": sum(_TOOL_WEIGHT.get(t.risk_level, 5) for t in allowed),
        "external_exposure": (15 if external and not locked else 6 if external else 0),
        "sensitive_reach": 10 * min(len(sens_cats), 3),
        "missing_approval": 8 * len(no_approval),
        "dangerous_paths": 12 * len(paths),
    }
    score = max(0, min(100, sum(breakdown.values())))
    level = "red" if score >= 60 else "orange" if score >= 30 else "green"

    accessible = sorted(set(sens_cats) | {d.kind for d in profile.data_sources})
    destinations = (
        list(profile.allowed_domains) if locked else (["ANY external host"] if external else [])
    )
    actions = sorted({t.name for t in allowed if t.high_impact or t.external})
    components = [
        BlastComponent(name=t.name, severity=_severity(t))
        for t in sorted(allowed, key=lambda t: _TOOL_WEIGHT.get(t.risk_level, 0), reverse=True)
    ]
    return BlastRadius(
        score=score,
        level=level,
        accessible_data=accessible,
        destinations=destinations,
        dangerous_actions=actions,
        components=components,
        paths=len(paths),
        breakdown=breakdown,
    )


# ----------------------------------------------------- risk-guided red teaming
def risk_guided_focus(profile: AgentProfile) -> list[RiskFocus]:
    """Rank attack families by the agent's real attack paths (most dangerous first)."""
    paths = attack_paths(profile)
    kinds = {p.kind for p in paths}
    focus: list[RiskFocus] = []
    if "indirect_injection_to_exfil" in kinds:
        focus.append(
            RiskFocus(
                family="Indirect Injection",
                priority=1,
                rationale="An untrusted source can reach an external-capable, sensitive path.",
            )
        )
    if "data_exfiltration" in kinds:
        focus.append(
            RiskFocus(
                family="Data Exfiltration",
                priority=len(focus) + 1,
                rationale="Sensitive data can be composed with an external send.",
            )
        )
    if "privilege_escalation" in kinds:
        focus.append(
            RiskFocus(
                family="Tool Abuse",
                priority=len(focus) + 1,
                rationale="A high-impact tool runs without human approval.",
            )
        )
    focus.append(
        RiskFocus(
            family="Prompt Injection",
            priority=len(focus) + 1,
            rationale="Baseline: every agent is probed for direct prompt injection.",
        )
    )
    return focus


_INTERNAL_DOMAIN = "company.com"


def hardened_profile(profile: AgentProfile) -> AgentProfile:
    """A copy of ``profile`` tightened the way ``generate-policy`` would: a locked
    domain allow-list and human approval on every high-impact tool."""
    hardened = profile.model_copy(deep=True)
    if not _domains_locked(hardened) and any(t.external for t in hardened.allowed_tool_profiles):
        hardened.allowed_domains = [_INTERNAL_DOMAIN]
    for tool in hardened.tools:
        if tool.high_impact:
            tool.requires_approval = True
    return hardened


class HardeningComparison(BaseModel):
    agent: str
    before: BlastRadius
    after: BlastRadius
    reduction: int  # points removed from the blast radius


def compare_hardening(profile: AgentProfile) -> HardeningComparison:
    """Blast radius now vs. after least-privilege tightening — the generator's payoff."""
    before = blast_radius(profile)
    after = blast_radius(hardened_profile(profile))
    return HardeningComparison(
        agent=profile.name,
        before=before,
        after=after,
        reduction=before.score - after.score,
    )


def analyze(target: str) -> AttackSurfaceReport:
    """Full attack-surface analysis for a scan target (agent / aegis.yaml / dir)."""
    profile = profile_target(target)
    return report_for(profile)


def report_for(profile: AgentProfile) -> AttackSurfaceReport:
    return AttackSurfaceReport(
        agent=profile.name,
        graph=build_graph(profile),
        paths=attack_paths(profile),
        blast_radius=blast_radius(profile),
        risk_guided=risk_guided_focus(profile),
    )

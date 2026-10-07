"""The AegisAI agent security scanner.

Discover an agent, assess it against seven risk categories, score it out of 100,
and generate a least-privilege ``aegis.yaml`` — the Discover → Assess → Configure
front half of the security lifecycle (``aegis audit`` / ``generate-policy``).

Nothing here is a new security control: discovery reads the real tool registry and
policies, scoring is a documented deterministic model, OWASP coverage comes from the
compliance service, and ``policy test`` runs the existing red-team sandbox.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from app.platform.policyfile import (
    AegisFile,
    AgentSection,
    ApprovalSection,
    DataSection,
    DomainsSection,
    PermissionsSection,
    TrustSection,
)
from app.policies.store import get_policy
from app.tools.gateway import get_tool_gateway
from app.tools.sandbox import IMPLEMENTATIONS

# Default sensitive-data categories to lock down when none are declared.
_DEFAULT_SENSITIVE = ["customer_records", "credentials"]
_INTERNAL_DOMAIN = "company.com"
_RISK_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


class ScannerError(ValueError):
    """The scan target could not be resolved."""


# --------------------------------------------------------------------- models
class ToolProfile(BaseModel):
    name: str
    risk_level: str = "MEDIUM"
    data_category: str | None = None
    external: bool = False  # has a domain-checked (URL/email) argument
    domain_kind: str | None = None
    requires_approval: bool = False
    min_trust: float = 0.0
    allowed: bool = True
    enabled: bool = True
    source: str = "registry"  # registry | discovered

    @property
    def high_impact(self) -> bool:
        """Needs a human in the loop: writes/sends outward, or is HIGH/CRITICAL."""
        return self.risk_level in ("HIGH", "CRITICAL") or self.domain_kind == "email"


class DataSource(BaseModel):
    name: str
    kind: str  # knowledge_base | database | web | file | vector_db | api
    trust: float | None = None
    untrusted: bool = False


class DataFlow(BaseModel):
    label: str
    sensitive: bool = False
    external: bool = False
    risk: str = "LOW"


class AgentProfile(BaseModel):
    name: str
    llm: str = "unknown"
    aegis_integrated: bool = True
    source: str = "agent"  # agent | aegis_yaml | directory
    tools: list[ToolProfile] = Field(default_factory=list)
    data_sources: list[DataSource] = Field(default_factory=list)
    external_destinations: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    sensitive_data: list[str] = Field(default_factory=list)
    trust_minimum: float = 0.0
    data_flows: list[DataFlow] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def allowed_tool_profiles(self) -> list[ToolProfile]:
        return [t for t in self.tools if t.allowed]


class RiskFinding(BaseModel):
    category: str
    severity: str  # LOW | MEDIUM | HIGH
    title: str
    detail: str
    fix: str | None = None
    owasp: str | None = None


class SecurityReport(BaseModel):
    agent: str
    score: int
    grade: str
    findings: list[RiskFinding]
    generated_policy: str  # aegis.yaml text
    owasp: list[dict] = Field(default_factory=list)
    attack_results: dict | None = None
    profile: AgentProfile


# ---------------------------------------------------------- scoring model
# Category weights sum to 100; a category's penalty = weight × severity multiplier.
WEIGHTS: dict[str, int] = {
    "Excessive Tool Permission": 18,
    "Missing Human Approval": 18,
    "Sensitive Data Exposure": 16,
    "Unsafe External Destinations": 14,
    "Indirect Injection": 12,
    "Prompt Injection": 12,
    "Output Leakage": 10,
}
_MULT = {"HIGH": 1.0, "MEDIUM": 0.5, "LOW": 0.0}
_OWASP = {
    "Prompt Injection": "LLM01",
    "Indirect Injection": "LLM01",
    "Excessive Tool Permission": "LLM06",
    "Sensitive Data Exposure": "LLM02",
    "Unsafe External Destinations": "LLM02",
    "Missing Human Approval": "LLM06",
    "Output Leakage": "LLM05",
}


# -------------------------------------------------------------- discovery
def _tool_profile(info, allowed: bool) -> ToolProfile:  # info: ToolInfo
    impl = IMPLEMENTATIONS.get(info.name)
    external = info.domain_checked_argument is not None
    return ToolProfile(
        name=info.name,
        risk_level=info.risk_level.value,
        data_category=info.data_category,
        external=external,
        domain_kind=(impl.domain_kind if impl and external else None),
        requires_approval=info.requires_approval,
        min_trust=info.required_trust,
        allowed=allowed,
        enabled=info.enabled,
        source="registry",
    )


def _data_sources_for(tool_names: list[str]) -> list[DataSource]:
    sources: list[DataSource] = []
    if "search_documents" in tool_names:
        sources.append(DataSource(name="knowledge base (RAG)", kind="knowledge_base"))
    if "read_database" in tool_names:
        sources.append(DataSource(name="finance database", kind="database"))
    if "web_fetch" in tool_names:
        sources.append(DataSource(name="external web pages", kind="web", untrusted=True))
    return sources


def _data_flows(tools: list[ToolProfile], allowed_domains: list[str]) -> list[DataFlow]:
    sensitive_cats = sorted({t.data_category for t in tools if t.data_category and t.allowed})
    has_sensitive = bool(sensitive_cats)
    locked = bool(allowed_domains)
    flows: list[DataFlow] = []
    for t in tools:
        if not (t.allowed and t.external):
            continue
        dest = f"allow-listed ({', '.join(allowed_domains)})" if locked else "any external host"
        risk = "HIGH" if (has_sensitive and not locked) else "MEDIUM" if has_sensitive else "LOW"
        label = f"{', '.join(sensitive_cats) or 'data'} → {t.name} → {dest}"
        flows.append(DataFlow(label=label, sensitive=has_sensitive, external=True, risk=risk))
    return flows


def profile_known_agent(name: str) -> AgentProfile:
    """Build an exact profile from a registered agent's policy + the tool registry."""
    policy = get_policy(name)
    if policy is None:
        raise ScannerError(f"No agent named '{name}'. Known agents come from the policy store.")
    described = {t.name: t for t in get_tool_gateway().describe()}
    tools = [
        _tool_profile(described[n], allowed=True) for n in policy.allowed_tools if n in described
    ]
    externals = [t.name for t in tools if t.external]
    return AgentProfile(
        name=policy.agent,
        llm="AegisAI runtime (Ollama or rule-based)",
        aegis_integrated=True,
        source="agent",
        tools=tools,
        data_sources=_data_sources_for(policy.allowed_tools),
        external_destinations=externals,
        allowed_tools=list(policy.allowed_tools),
        allowed_domains=list(policy.allowed_domains),
        sensitive_data=list(policy.sensitive_data),
        trust_minimum=max((t.min_trust for t in tools), default=0.0),
        data_flows=_data_flows(tools, policy.allowed_domains),
    )


def profile_aegis_file(path: str | Path) -> AgentProfile:
    """Profile an ``aegis.yaml`` by mapping its tools onto the registry."""
    from app.platform.policyfile import load_aegis_file

    file = load_aegis_file(path)
    described = {t.name: t for t in get_tool_gateway().describe()}
    approval = set(file.approval.required_for)
    tools: list[ToolProfile] = []
    for n in file.permissions.tools:
        if n in described:
            tp = _tool_profile(described[n], allowed=True)
            tp.requires_approval = tp.requires_approval or n in approval
            if file.trust.minimum:
                tp.min_trust = max(tp.min_trust, file.trust.minimum)
            tools.append(tp)
        else:
            tools.append(ToolProfile(name=n, source="discovered", requires_approval=n in approval))
    externals = [t.name for t in tools if t.external]
    return AgentProfile(
        name=file.agent.name,
        llm="AegisAI runtime (Ollama or rule-based)",
        aegis_integrated=True,
        source="aegis_yaml",
        tools=tools,
        data_sources=_data_sources_for(file.permissions.tools),
        external_destinations=externals,
        allowed_tools=list(file.permissions.tools),
        allowed_domains=list(file.domains.allowed),
        sensitive_data=list(file.data.deny),
        trust_minimum=file.trust.minimum,
        data_flows=_data_flows(tools, file.domains.allowed),
    )


# ---- directory discovery (heuristic static scan) -------------------------
_TEXT_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".md", ".txt", ".toml"}
_LLM_SIGNS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "ollama": "Ollama",
    "langchain": "LangChain",
    "langgraph": "LangGraph",
    "llama_index": "LlamaIndex",
    "gemini": "Google Gemini",
    "mistral": "Mistral",
}
_SOURCE_SIGNS = {
    "vector_db": ("chroma", "faiss", "pinecone", "pgvector", "weaviate", "qdrant", "milvus"),
    "database": ("sqlite", "psycopg", "postgres", "mysql", "sqlalchemy", "mongodb"),
    "file": ("pdfplumber", "pypdf", "open(", "pathlib", ".read_text", "docx"),
    "api": ("requests.", "httpx", "aiohttp", "urllib"),
}
# Common agent-tool names beyond the AegisAI registry.
_EXTRA_TOOLS = {
    "send_mail": ("email",),
    "send_message": ("email",),
    "web_search": (),
    "http_request": ("url",),
    "file_access": (),
    "read_file": (),
    "write_file": (),
    "database_query": (),
    "query_customer": (),
    "get_invoice": (),
    "export_report": (),
    "export_data": ("url",),
}
_URL_RE = re.compile(r"https?://([A-Za-z0-9.-]+)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def profile_directory(path: str | Path) -> AgentProfile:
    """Best-effort static discovery of an agent from its source directory."""
    root = Path(path)
    if not root.exists():
        raise ScannerError(f"Path not found: {root}")
    registry = {t.name: t for t in get_tool_gateway().describe()}
    found_tools: dict[str, bool] = {}  # name -> known-in-registry
    llm = "unknown"
    source_kinds: set[str] = set()
    hosts: set[str] = set()
    email_domains: set[str] = set()
    aegis_yaml: Path | None = None
    scanned = 0

    for file in sorted(root.rglob("*")):
        if aegis_yaml is None and file.name == "aegis.yaml":
            aegis_yaml = file
        if not file.is_file() or file.suffix.lower() not in _TEXT_EXT:
            continue
        if any(part in {".git", "node_modules", ".venv", "dist", "__pycache__"} for part in file.parts):
            continue
        try:
            text = file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if len(text) > 400_000:  # skip very large/generated files
            continue
        scanned += 1
        low = text.lower()
        for name in list(registry) + list(_EXTRA_TOOLS):
            if name in found_tools:
                continue
            if re.search(rf"\b{re.escape(name)}\b", text):
                found_tools[name] = name in registry
        if llm == "unknown":
            for sign, label in _LLM_SIGNS.items():
                if sign in low:
                    llm = label
                    break
        for kind, signs in _SOURCE_SIGNS.items():
            if any(s in low for s in signs):
                source_kinds.add(kind)
        for m in _URL_RE.finditer(text):
            hosts.add(m.group(1).lower())
        for m in _EMAIL_RE.finditer(text):
            email_domains.add(m.group(1).lower())

    # An aegis.yaml in the tree means the agent is already AegisAI-integrated.
    if aegis_yaml is not None:
        base = profile_aegis_file(aegis_yaml)
        base.source = "directory"
        base.llm = llm if llm != "unknown" else base.llm
        base.notes.append(f"Found aegis.yaml at {aegis_yaml}; treated as AegisAI-integrated.")
        base.notes.append(f"Scanned {scanned} source file(s).")
        return base

    tools: list[ToolProfile] = []
    for name, known in found_tools.items():
        if known:
            tp = _tool_profile(registry[name], allowed=True)
            tp.source = "discovered"
        else:
            hints = _EXTRA_TOOLS.get(name, ())
            is_email = "email" in hints
            is_url = "url" in hints or name in {"web_search", "http_request"}
            tp = ToolProfile(
                name=name,
                risk_level="HIGH" if (is_email or name in {"export_data", "write_file"}) else "MEDIUM",
                external=is_email or is_url,
                domain_kind="email" if is_email else ("url" if is_url else None),
                requires_approval=False,
                source="discovered",
            )
        tools.append(tp)

    data_sources: list[DataSource] = [
        DataSource(name=f"{kind.replace('_', ' ')} source", kind=kind, untrusted=(kind in {"web", "api"}))
        for kind in sorted(source_kinds)
    ]
    external_hosts = sorted(h for h in hosts if not h.endswith("localhost"))
    notes = [
        f"Heuristic scan of {scanned} source file(s) — results are best-effort, not exhaustive.",
        "No aegis.yaml found: the agent is NOT behind AegisAI (no input firewall, guarded RAG or output DLP).",
    ]
    if external_hosts:
        notes.append("External hosts referenced: " + ", ".join(external_hosts[:8]))

    return AgentProfile(
        name=root.resolve().name or "discovered-agent",
        llm=llm,
        aegis_integrated=False,
        source="directory",
        tools=tools,
        data_sources=data_sources,
        external_destinations=[t.name for t in tools if t.external],
        allowed_tools=[t.name for t in tools],
        allowed_domains=[],
        sensitive_data=[],
        trust_minimum=0.0,
        data_flows=_data_flows(tools, []),
        notes=notes,
    )


def profile_target(target: str) -> AgentProfile:
    """Resolve a scan target: a known agent name, an aegis.yaml, or a directory."""
    p = Path(target)
    if p.is_dir():
        return profile_directory(p)
    if p.is_file():
        return profile_aegis_file(p)
    if get_policy(target) is not None:
        return profile_known_agent(target)
    if target.startswith(("http://", "https://")):
        raise ScannerError(
            "Live-URL auditing isn't supported yet. Point `aegis audit` at an agent name, "
            "an aegis.yaml, or an agent source directory."
        )
    raise ScannerError(
        f"Could not resolve '{target}' as a known agent, an aegis.yaml file, or a directory."
    )


# -------------------------------------------------------------- assessment
def _finding(category: str, severity: str, title: str, detail: str, fix: str | None) -> RiskFinding:
    return RiskFinding(
        category=category,
        severity=severity,
        title=title,
        detail=detail,
        fix=fix,
        owasp=_OWASP.get(category),
    )


def assess(profile: AgentProfile) -> list[RiskFinding]:
    """Evaluate the profile against the seven risk categories (deterministic)."""
    allowed = profile.allowed_tool_profiles
    integrated = profile.aegis_integrated
    findings: list[RiskFinding] = []
    # A wildcard allow-list ("*") is effectively no allow-list at all.
    domains_locked = bool(profile.allowed_domains) and "*" not in profile.allowed_domains

    # 1. Excessive Tool Permission
    crit = [t for t in allowed if t.risk_level == "CRITICAL"]
    high = [t for t in allowed if t.risk_level == "HIGH"]
    if crit:
        sev, detail = "HIGH", f"Allows CRITICAL-risk tool(s): {', '.join(t.name for t in crit)}."
    elif len(high) >= 2:
        sev, detail = "HIGH", f"Allows several HIGH-risk tools: {', '.join(t.name for t in high)}."
    elif len(high) == 1:
        sev, detail = "MEDIUM", f"Allows a HIGH-risk tool: {high[0].name}."
    else:
        sev, detail = "LOW", "No HIGH or CRITICAL tools are allowed."
    findings.append(
        _finding(
            "Excessive Tool Permission", sev, "Tool permissions", detail,
            "Remove unneeded high-risk tools from permissions.tools (deny by default).",
        )
    )

    # 2. Missing Human Approval
    gap = [t for t in allowed if t.high_impact and not t.requires_approval]
    if gap:
        findings.append(
            _finding(
                "Missing Human Approval", "HIGH", "Human approval",
                f"High-impact tool(s) run without approval: {', '.join(t.name for t in gap)}.",
                "approval:\n  required_for:\n    - " + "\n    - ".join(t.name for t in gap),
            )
        )
    else:
        findings.append(
            _finding("Missing Human Approval", "LOW", "Human approval",
                     "High-impact tools require human approval (or none are present).", None)
        )

    # 3. Sensitive Data Exposure
    sens_tools = [t for t in allowed if t.data_category]
    sens_cats = sorted({t.data_category for t in sens_tools if t.data_category})
    exfil_unlocked = any(t.external for t in allowed) and not domains_locked
    if sens_tools and not profile.sensitive_data:
        findings.append(
            _finding(
                "Sensitive Data Exposure", "HIGH", "Sensitive data",
                f"Touches sensitive data ({', '.join(sens_cats)}) but declares no DLP categories.",
                "data:\n  deny:\n    - " + "\n    - ".join(sens_cats or _DEFAULT_SENSITIVE),
            )
        )
    elif sens_tools and exfil_unlocked:
        findings.append(
            _finding("Sensitive Data Exposure", "MEDIUM", "Sensitive data",
                     "Sensitive data could leave via an external tool with no domain allow-list.",
                     "Lock domains.allowed and keep data.deny populated."),
        )
    else:
        findings.append(
            _finding("Sensitive Data Exposure", "LOW", "Sensitive data",
                     "Sensitive data categories are declared and redacted by DLP." if profile.sensitive_data
                     else "No sensitive data categories are handled.", None)
        )

    # 4. Unsafe External Destinations
    ext = [t for t in allowed if t.external]
    wildcard = bool(profile.allowed_domains) and "*" in profile.allowed_domains
    if ext and not domains_locked:
        detail = (
            f"External-capable tool(s) allow ANY destination (domains.allowed is '*'): "
            f"{', '.join(t.name for t in ext)}."
            if wildcard
            else f"External-capable tool(s) have no domain allow-list: {', '.join(t.name for t in ext)}."
        )
        findings.append(
            _finding(
                "Unsafe External Destinations", "HIGH", "External destinations",
                detail,
                "domains:\n  allowed:\n    - " + _INTERNAL_DOMAIN,
            )
        )
    elif ext:
        findings.append(
            _finding("Unsafe External Destinations", "LOW", "External destinations",
                     f"External destinations are restricted to {', '.join(profile.allowed_domains)}.", None)
        )
    else:
        findings.append(
            _finding("Unsafe External Destinations", "LOW", "External destinations",
                     "No tools can reach external destinations.", None)
        )

    # 5. Indirect Injection
    untrusted = any(d.untrusted for d in profile.data_sources) or "web_fetch" in profile.allowed_tools
    if untrusted and not integrated:
        findings.append(
            _finding("Indirect Injection", "HIGH", "Indirect injection",
                     "Reads untrusted external content with no guarded retrieval / output screening.",
                     "Route retrieval + tool output through AegisAI (guarded RAG quarantines injected chunks)."),
        )
    elif untrusted:
        findings.append(
            _finding("Indirect Injection", "MEDIUM", "Indirect injection",
                     "Reads untrusted external content; guarded RAG + output screening reduce but don't eliminate the risk.",
                     None)
        )
    else:
        findings.append(
            _finding("Indirect Injection", "LOW", "Indirect injection",
                     "No untrusted external data sources.", None)
        )

    # 6. Prompt Injection
    if not integrated:
        findings.append(
            _finding("Prompt Injection", "HIGH", "Prompt injection",
                     "No input firewall in front of the model — user input reaches it unscreened.",
                     "Wrap the agent with AegisAI (SecureAgent / the /v1/secure gateway) to screen every message."),
        )
    else:
        findings.append(
            _finding("Prompt Injection", "LOW", "Prompt injection",
                     "Every message is screened by the input firewall.", None)
        )

    # 7. Output Leakage
    handles_sensitive = bool(sens_tools) or bool(profile.sensitive_data)
    if handles_sensitive and not integrated:
        findings.append(
            _finding("Output Leakage", "HIGH", "Output leakage",
                     "Sensitive data can leave in answers with no output DLP.",
                     "Enable AegisAI's output guard (DLP) by routing responses through the gateway."),
        )
    elif handles_sensitive and not profile.sensitive_data:
        findings.append(
            _finding("Output Leakage", "MEDIUM", "Output leakage",
                     "DLP is present but no sensitive categories are declared to redact.",
                     "Populate data.deny so DLP knows what to redact."),
        )
    else:
        findings.append(
            _finding("Output Leakage", "LOW", "Output leakage",
                     "Secrets and declared PII are redacted from outputs.", None)
        )

    return findings


def _grade(score: int) -> str:
    return "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "F"


def _owasp_summary() -> list[dict]:
    try:
        from app.compliance.service import coverage_report

        report = coverage_report()
        framework = next((f for f in report.frameworks if "OWASP" in f.name), None)
        if framework is None:
            return []
        return [{"id": i.id, "name": i.name, "status": i.status} for i in framework.items]
    except Exception:  # noqa: BLE001 — coverage is a nice-to-have in the report
        return []


def generate_policy(profile: AgentProfile) -> AegisFile:
    """Produce a least-privilege ``aegis.yaml`` for the profiled agent."""
    allowed = profile.allowed_tool_profiles or profile.tools
    tool_names = [t.name for t in allowed]
    data_deny = sorted({t.data_category for t in allowed if t.data_category}) or (
        _DEFAULT_SENSITIVE if any(t.data_category for t in allowed) else list(profile.sensitive_data)
    )
    approval = sorted({t.name for t in allowed if t.high_impact})
    needs_domains = any(t.external for t in allowed)
    domains = list(profile.allowed_domains) or ([_INTERNAL_DOMAIN] if needs_domains else [])
    return AegisFile(
        agent=AgentSection(name=profile.name),
        permissions=PermissionsSection(tools=tool_names),
        domains=DomainsSection(allowed=domains),
        data=DataSection(allow=[], deny=data_deny),
        trust=TrustSection(minimum=0.70),
        approval=ApprovalSection(required_for=approval),
    )


def score_report(profile: AgentProfile, attack_results: dict | None = None) -> SecurityReport:
    """Assemble the full security report for a profile."""
    findings = assess(profile)
    penalty = sum(WEIGHTS[f.category] * _MULT[f.severity] for f in findings)
    score = max(0, min(100, round(100 - penalty)))
    # Report findings worst-first.
    findings.sort(key=lambda f: _RISK_RANK.get(f.severity, 0), reverse=True)
    return SecurityReport(
        agent=profile.name,
        score=score,
        grade=_grade(score),
        findings=findings,
        generated_policy=generate_policy(profile).to_yaml(),
        owasp=_owasp_summary(),
        attack_results=attack_results,
        profile=profile,
    )


def audit(target: str) -> SecurityReport:
    """Discover ``target`` and return its security report (the main entry point)."""
    return score_report(profile_target(target))


# ---------------------------------------------------------------- HTML report
_SEV_COLOR = {"HIGH": "#d03b3b", "MEDIUM": "#aa7416", "LOW": "#278361"}


def render_html(report: SecurityReport) -> str:
    """A self-contained HTML security report (for ``aegis audit --html``)."""
    import html

    p = report.profile
    ring = "#278361" if report.score >= 80 else "#aa7416" if report.score >= 60 else "#d03b3b"
    rows = "".join(
        f'<tr><td><span class="dot" style="background:{_SEV_COLOR[f.severity]}"></span>{html.escape(f.severity)}</td>'
        f"<td>{html.escape(f.category)}</td><td>{html.escape(f.detail)}</td>"
        f"<td>{html.escape(f.owasp or '')}</td></tr>"
        for f in report.findings
    )
    fixes = "".join(
        f"<div class='fix'><b>{html.escape(f.category)}</b><pre>{html.escape(f.fix)}</pre></div>"
        for f in report.findings
        if f.fix and f.severity != "LOW"
    )
    notes = "".join(f"<li>{html.escape(n)}</li>" for n in p.notes)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>AegisAI Security Report — {html.escape(report.agent)}</title>
<style>
body{{font:14px/1.6 system-ui,Segoe UI,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;color:#192b32}}
h1{{font-size:20px;margin:0}} .sub{{color:#677981;margin:.25rem 0 1.5rem}}
.score{{font-size:52px;font-weight:700;color:{ring}}} .grade{{color:#677981;font-size:18px}}
table{{border-collapse:collapse;width:100%;margin:1rem 0}} th,td{{text-align:left;padding:.5rem;border-bottom:1px solid #e5e7ec;vertical-align:top}}
th{{color:#677981;font-size:12px;text-transform:uppercase;letter-spacing:.04em}}
.dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}}
pre{{background:#f1f4f5;border:1px solid #e5e7ec;border-radius:8px;padding:.75rem;overflow:auto;font-size:12px}}
.fix{{margin:.75rem 0}} .meta{{color:#677981;font-size:12px}}
</style></head><body>
<h1>🛡️ AegisAI Security Report</h1>
<div class="sub">{html.escape(report.agent)} · discovered via {html.escape(p.source)} · LLM: {html.escape(p.llm)}</div>
<div class="score">{report.score}<span style="font-size:20px;color:#677981">/100</span> <span class="grade">({report.grade})</span></div>
<h2>Risk findings</h2>
<table><thead><tr><th>Severity</th><th>Category</th><th>Detail</th><th>OWASP</th></tr></thead><tbody>{rows}</tbody></table>
{"<h2>Recommended fixes</h2>" + fixes if fixes else ""}
<h2>Generated policy (aegis.yaml)</h2><pre>{html.escape(report.generated_policy)}</pre>
{"<h2>Scan notes</h2><ul class='meta'>" + notes + "</ul>" if notes else ""}
<p class="meta">Generated by AegisAI — the model proposes, the gateway disposes.</p>
</body></html>"""

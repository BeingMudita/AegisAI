"""Threat-coverage catalog: AegisAI controls mapped to industry frameworks.

* OWASP Top 10 for LLM Applications (2025) — https://genai.owasp.org/llm-top-10/
* MITRE ATLAS — https://atlas.mitre.org/ (technique IDs as published; ATLAS
  revises names and IDs between releases, so re-check when updating).

Statuses are deliberately conservative:
  ``mitigated`` — controls address the threat and red-team evidence exercises them;
  ``partial``   — part of the threat is addressed, the rest is named in ``residual``;
  ``gap``       — not addressed by AegisAI today.

Evidence references red-team firewall categories (``category:<name>``), agent
scenarios (``scenario:<id>``) or unit tests (``test:<path>``). Category and
scenario evidence is checked live against the latest red-team run.
"""

from __future__ import annotations

from typing import TypedDict

from app.compliance.schemas import Control, ThreatDef


class FrameworkDef(TypedDict):
    id: str
    name: str
    version: str
    url: str
    items: list[ThreatDef]


CONTROLS: list[Control] = [
    Control(
        id="FIREWALL",
        name="Prompt-injection firewall",
        description="Weighted signatures scored on every channel: user input, retrieved chunks, tool arguments and tool output.",
        page="firewall",
        code=["backend/app/firewall/scanner.py", "backend/app/firewall/rules.py"],
    ),
    Control(
        id="NORMALIZE",
        name="Obfuscation normalization",
        description="Undoes zero-width and bidi characters, homoglyphs, leetspeak, spaced letters and base64 before matching.",
        page="firewall",
        code=["backend/app/firewall/normalize.py"],
    ),
    Control(
        id="SPOTLIGHT",
        name="Data spotlighting",
        description="Retrieved and tool text is wrapped in <data> tags, HTML-escaped so it cannot close the tag, and declared non-executable in LLM prompts.",
        code=["backend/app/agents/brain.py"],
    ),
    Control(
        id="GATEWAY",
        name="Zero-trust tool gateway",
        description="Single execution path: registry kill switch, deny-by-default agent policy, firewall on arguments.",
        page="policies",
        code=["backend/app/tools/gateway.py", "backend/app/policies/engine.py"],
    ),
    Control(
        id="DOMAIN",
        name="Domain allow-lists",
        description="URL and email arguments must name exactly one destination (one https URL, one plain address) on an approved domain (subdomains included).",
        page="policies",
        code=["backend/app/tools/gateway.py"],
    ),
    Control(
        id="TRUST",
        name="Dynamic trust scoring",
        description="Attacks and violations lower the agent's trust with the principal driving it, so one user can't suspend a shared agent for everyone; every tool has a minimum; below 0.2 the agent is suspended for that principal.",
        page="trust",
        code=["backend/app/trust/engine.py", "backend/app/trust/scoring.py"],
    ),
    Control(
        id="APPROVAL",
        name="Human approval",
        description="High-impact tools wait for an administrator; every checkpoint is re-verified at approval time.",
        page="approvals",
        code=["backend/app/tools/gateway.py", "backend/app/api/routes/approvals.py"],
    ),
    Control(
        id="LIMITS",
        name="Rate and step limits",
        description="Per-agent tool rate limits, login throttling, a cap on tool steps per turn, upload and message size limits.",
        code=["backend/app/persistence/ratelimit.py", "backend/app/auth/limiter.py"],
    ),
    Control(
        id="BUDGETS",
        name="Per-principal budgets",
        description="Every user and API caller has daily turn, token and cost budgets (policy-as-code, with role and principal overrides), reserved atomically before a turn and charged with the tokens the LLM reports; each LLM call's output is capped. A used-up budget is a 429 until it resets, and the first refusal of the day is an ANOMALY event.",
        code=["backend/app/quotas/service.py", "backend/app/policies/default_policies.yaml"],
    ),
    Control(
        id="DLP",
        name="Data-loss prevention",
        description="Secrets are always redacted; PII is redacted when the agent's policy marks the data as sensitive. Applies to tool output, answers, and the text an email or upload sends out.",
        code=["backend/app/firewall/dlp.py"],
    ),
    Control(
        id="OUTPUT_GUARD",
        name="Output guard and safe rendering",
        description="Exfiltration links are stripped from answers; the dashboard renders agent text as React elements, never HTML.",
        code=["backend/app/agents/runtime.py", "frontend/src/components/ui.tsx"],
    ),
    Control(
        id="RAG_QUARANTINE",
        name="Ingestion screening",
        description="Every chunk is scanned before indexing; injected paragraphs are quarantined and their source penalized.",
        page="knowledge",
        code=["backend/app/rag/knowledge_base.py"],
    ),
    Control(
        id="SOURCE_TRUST",
        name="Source trust filtering",
        description="Untrusted or degraded sources never reach the agent; chunks are re-scanned at retrieval.",
        page="knowledge",
        code=["backend/app/rag/knowledge_base.py"],
    ),
    Control(
        id="SANDBOX",
        name="Sandboxed tools",
        description="Tools are simulations: no real shell, network or email; the shell and upload tools are disabled outright.",
        code=["backend/app/tools/sandbox.py"],
    ),
    Control(
        id="AUDIT",
        name="Durable audit log",
        description="Every decision is counted and every incident recorded; the Postgres log cannot be erased through the API, only aged out by the retention policy.",
        page="events",
        code=["backend/app/telemetry/store.py", "backend/app/persistence/audit.py"],
    ),
    Control(
        id="ACCESS",
        name="Authenticated, role-based API",
        description="JWT auth, three roles, ownership checks, login throttling per address and per account, refusal to start with development secrets.",
        code=["backend/app/auth/", "backend/app/main.py"],
    ),
    Control(
        id="REDTEAM",
        name="Continuous red-team evaluation",
        description="Labelled attack suites run in CI as a security gate and on demand from the Red-team lab; a held-out set the rules were never tuned on is scored separately.",
        page="redteam",
        code=["backend/app/redteam/runner.py", "attack-scenarios/"],
    ),
    Control(
        id="DEPENDENCIES",
        name="Pinned and scanned dependencies",
        description="Every runtime package is pinned with hashes in requirements.lock and every CI action to a commit SHA; CI scans Python and npm dependencies and both container images (Trivy: fixable HIGH/CRITICAL fail the build, Dockerfiles checked for misconfiguration) and publishes CycloneDX SBOMs of the code and the images; Dependabot proposes updates.",
        code=[
            "backend/requirements.lock",
            ".github/workflows/ci.yml",
            ".github/dependabot.yml",
            ".trivyignore",
        ],
    ),
    Control(
        id="PROVENANCE",
        name="Model provenance",
        description="Models are pinned in a manifest: Hugging Face models by commit and the SHA-256 of every file, verified before loading from that verified copy; Ollama models by manifest digest. Unpinned or altered models are refused (MODEL_PROVENANCE=enforce) and raise an ANOMALY event; the pins are published as a CycloneDX AI-BOM.",
        code=[
            "backend/model-manifest.yaml",
            "backend/app/supply_chain/provenance.py",
            "backend/app/supply_chain/aibom.py",
        ],
    ),
]

OWASP_LLM_2025: list[ThreatDef] = [
    ThreatDef(
        id="LLM01",
        name="Prompt Injection",
        description="Inputs that alter the model's behaviour, directly from the user or indirectly through content it processes.",
        status="mitigated",
        controls=["FIREWALL", "NORMALIZE", "SPOTLIGHT", "RAG_QUARANTINE", "GATEWAY", "TRUST"],
        evidence=[
            "category:instruction_override",
            "category:role_hijack",
            "category:delimiter_injection",
            "category:indirect_injection",
            "category:obfuscation",
            "scenario:AG-10",
            "scenario:AG-12",
            "scenario:AG-13",
            "scenario:AG-30",
            "scenario:AG-31",
        ],
        residual="Signature detection misses paraphrased attacks without trigger words (the Red-team lab's held-out set measures how many); the gateway limits what they can make an agent do.",
    ),
    ThreatDef(
        id="LLM02",
        name="Sensitive Information Disclosure",
        description="Leaking personal data, credentials or confidential business data through outputs or actions.",
        status="mitigated",
        controls=["DLP", "DOMAIN", "FIREWALL", "GATEWAY", "OUTPUT_GUARD"],
        evidence=[
            "category:data_exfiltration",
            "category:credential_harvesting",
            "scenario:AG-03",
            "scenario:AG-20",
            "scenario:AG-24",
        ],
        residual="DLP is pattern-based (emails, phones, cards, SSNs, keys); free-text secrets without a recognisable shape can pass.",
    ),
    ThreatDef(
        id="LLM03",
        name="Supply Chain",
        description="Compromised models, datasets, packages or plugins.",
        status="mitigated",
        controls=["DEPENDENCIES", "PROVENANCE", "REDTEAM"],
        evidence=[
            "test:backend/tests/test_supply_chain.py",
            "test:backend/tests/test_evaluation.py",
        ],
        residual="Pins prove a model is the reviewed one, not that its publisher is trustworthy: there is no publisher-signature (e.g. Sigstore) verification, and training-data provenance is out of scope. Image scanning covers known CVEs only.",
    ),
    ThreatDef(
        id="LLM04",
        name="Data and Model Poisoning",
        description="Manipulated training, fine-tuning or retrieval data that plants backdoors or bias.",
        status="partial",
        controls=["RAG_QUARANTINE", "SOURCE_TRUST", "TRUST"],
        evidence=[
            "category:indirect_injection",
            "scenario:AG-31",
            "test:backend/tests/test_rag.py",
        ],
        residual="Covers poisoned retrieval data only; training-data and model poisoning are out of scope.",
    ),
    ThreatDef(
        id="LLM05",
        name="Improper Output Handling",
        description="Passing model output to downstream systems or browsers without validation.",
        status="mitigated",
        controls=["OUTPUT_GUARD", "FIREWALL", "DLP"],
        evidence=[
            "category:data_exfiltration",
            "scenario:AG-30",
            "test:backend/tests/test_agents.py",
        ],
        residual="Output feeds only the dashboard and sandboxed tools; real integrations would need their own validation.",
    ),
    ThreatDef(
        id="LLM06",
        name="Excessive Agency",
        description="Agents with more functionality, permissions or autonomy than their task requires.",
        status="mitigated",
        controls=["GATEWAY", "DOMAIN", "TRUST", "APPROVAL", "LIMITS", "SANDBOX"],
        evidence=[
            "category:tool_abuse",
            "scenario:AG-06",
            "scenario:AG-21",
            "scenario:AG-22",
            "scenario:AG-23",
            "scenario:AG-24",
            "scenario:AG-25",
            "scenario:AG-26",
            "scenario:AG-40",
            "scenario:AG-41",
        ],
        residual="Policies are per agent, not per end user; delegated user permissions arrive with SSO and tenancy.",
    ),
    ThreatDef(
        id="LLM07",
        name="System Prompt Leakage",
        description="Extracting the system prompt or the secrets and rules embedded in it.",
        status="mitigated",
        controls=["FIREWALL", "NORMALIZE", "TRUST"],
        evidence=["category:prompt_exfiltration", "scenario:AG-11", "scenario:AG-13"],
        residual="System prompts hold no secrets by design; paraphrased extraction attempts may still pass the firewall.",
    ),
    ThreatDef(
        id="LLM08",
        name="Vector and Embedding Weaknesses",
        description="Weaknesses in how embeddings are generated, stored or retrieved (poisoning, leakage, mixed access).",
        status="partial",
        controls=["SOURCE_TRUST", "RAG_QUARANTINE", "ACCESS"],
        evidence=["scenario:AG-31", "test:backend/tests/test_ingestion.py"],
        residual="Admin-only ingestion and embedding-model consistency checks; no per-tenant vector isolation until tenancy lands.",
    ),
    ThreatDef(
        id="LLM09",
        name="Misinformation",
        description="False or misleading output presented as fact.",
        status="partial",
        controls=["SOURCE_TRUST", "RAG_QUARANTINE"],
        evidence=["scenario:AG-01", "scenario:AG-04", "scenario:AG-31"],
        residual="Answers cite retrieved, trust-filtered sources; there is no automated fact verification.",
    ),
    ThreatDef(
        id="LLM10",
        name="Unbounded Consumption",
        description="Excessive or uncontrolled resource use leading to denial of service or cost blow-ups.",
        status="mitigated",
        controls=["BUDGETS", "LIMITS", "ACCESS"],
        evidence=[
            "test:backend/tests/test_quotas_retention.py",
            "test:backend/tests/test_tool_gateway.py",
            "test:backend/tests/test_auth_limits.py",
        ],
        residual="Budgets are per principal, so many accounts can still add up; there is no global capacity limit. Token counts are estimates when no LLM reports them.",
    ),
]

MITRE_ATLAS: list[ThreatDef] = [
    ThreatDef(
        id="AML.T0051.000",
        name="LLM Prompt Injection: Direct",
        description="An adversary crafts input that subverts the model's instructions.",
        status="mitigated",
        controls=["FIREWALL", "NORMALIZE", "TRUST"],
        evidence=[
            "category:instruction_override",
            "category:obfuscation",
            "scenario:AG-10",
            "scenario:AG-12",
        ],
        residual="Paraphrased direct injections without trigger words.",
    ),
    ThreatDef(
        id="AML.T0051.001",
        name="LLM Prompt Injection: Indirect",
        description="Instructions planted in data the model later processes — documents, web pages, tool output.",
        status="mitigated",
        controls=["FIREWALL", "RAG_QUARANTINE", "SPOTLIGHT", "GATEWAY"],
        evidence=["category:indirect_injection", "scenario:AG-30", "scenario:AG-31"],
        residual="Indirect instructions phrased as ordinary prose.",
    ),
    ThreatDef(
        id="AML.T0054",
        name="LLM Jailbreak",
        description="Prompts that bypass the model's safety constraints (personas, developer modes).",
        status="mitigated",
        controls=["FIREWALL", "TRUST"],
        evidence=["category:role_hijack", "scenario:AG-10"],
        residual="Novel personas without known markers.",
    ),
    ThreatDef(
        id="AML.T0056",
        name="LLM Meta Prompt Extraction",
        description="Extracting the system prompt or instructions.",
        status="mitigated",
        controls=["FIREWALL"],
        evidence=["category:prompt_exfiltration", "scenario:AG-11"],
        residual="Indirect extraction through paraphrase.",
    ),
    ThreatDef(
        id="AML.T0057",
        name="LLM Data Leakage",
        description="Getting the model to reveal sensitive data it can access.",
        status="mitigated",
        controls=["DLP", "DOMAIN", "GATEWAY"],
        evidence=["category:data_exfiltration", "scenario:AG-03", "scenario:AG-20"],
        residual="Unstructured secrets that DLP patterns don't recognise.",
    ),
    ThreatDef(
        id="AML.T0053",
        name="LLM Plugin Compromise",
        description="Abusing the tools an LLM can invoke to act on the adversary's behalf.",
        status="mitigated",
        controls=["GATEWAY", "APPROVAL", "TRUST", "SANDBOX", "DOMAIN"],
        evidence=["category:tool_abuse", "scenario:AG-22", "scenario:AG-23", "scenario:AG-06"],
        residual="Applies to the sandboxed tool set; real adapters need the same review.",
    ),
    ThreatDef(
        id="AML.T0070",
        name="RAG Poisoning",
        description="Injecting malicious content into a retrieval corpus.",
        status="mitigated",
        controls=["RAG_QUARANTINE", "SOURCE_TRUST"],
        evidence=["scenario:AG-31", "test:backend/tests/test_rag.py"],
        residual="Benign-looking but false content (misinformation) is not detected.",
    ),
    ThreatDef(
        id="AML.T0068",
        name="LLM Prompt Obfuscation",
        description="Hiding instructions from defences with encoding, invisible characters or look-alike text.",
        status="mitigated",
        controls=["NORMALIZE", "FIREWALL"],
        evidence=["category:obfuscation", "scenario:AG-12", "scenario:AG-13"],
        residual="Encodings beyond base64 (e.g. ROT13, other languages) are not decoded.",
    ),
    ThreatDef(
        id="AML.T0010",
        name="ML Supply Chain Compromise",
        description="Tampered models, model hubs or software dependencies introduced before deployment.",
        status="mitigated",
        controls=["PROVENANCE", "DEPENDENCIES"],
        evidence=["test:backend/tests/test_supply_chain.py"],
        residual="Integrity is checked against reviewed pins; publisher signatures are not verified.",
    ),
    ThreatDef(
        id="AML.T0029",
        name="Denial of ML Service",
        description="Exhausting the system's resources to degrade or deny service.",
        status="partial",
        controls=["BUDGETS", "LIMITS"],
        evidence=[
            "test:backend/tests/test_quotas_retention.py",
            "test:backend/tests/test_tool_gateway.py",
            "test:backend/tests/test_auth_limits.py",
        ],
        residual="Per-principal budgets bound each caller, not the system: production still needs edge rate limiting and a global capacity limit.",
    ),
]

FRAMEWORKS: list[FrameworkDef] = [
    {
        "id": "owasp-llm-2025",
        "name": "OWASP Top 10 for LLM Applications",
        "version": "2025",
        "url": "https://genai.owasp.org/llm-top-10/",
        "items": OWASP_LLM_2025,
    },
    {
        "id": "mitre-atlas",
        "name": "MITRE ATLAS",
        "version": "techniques relevant to LLM agents",
        "url": "https://atlas.mitre.org/",
        "items": MITRE_ATLAS,
    },
]

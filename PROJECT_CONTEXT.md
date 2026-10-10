# AegisAI — Project Context File

> **Purpose of this file.** This is the single, self-contained context document for the
> AegisAI project. It is written so that **any AI agent (or new engineer) can read this one
> file and understand the entire project** — what it is, why it exists, how it is built, what
> is done, what is not, and where it is going. It is the canonical, living summary that sits
> above the code, the README and the per-topic docs.
>
> **It is a map, not the territory.** When this file and the code disagree, the code wins —
> verify file paths, flags and numbers against the current source before relying on them, and
> then fix this file.

---

## 0. How to use and maintain this file

### For an agent reading this file
1. Read sections 1–4 for the mental model (what/why/how).
2. Use section 5 (repository map) and section 8 (APIs) / 9 (CLI) to locate things.
3. Check section 14 (history) and 15 (current state) to know what already exists before building.
4. Respect section 18 (design rules & gotchas) — these are hard constraints learned the hard way.

### MAINTENANCE PROTOCOL — keep this file current (read before editing it)
This file must be updated whenever the project changes in a way that affects the sections below.
**After any significant change** (a new module, feature, engine, page, API, dependency, phase,
evaluation result, or design decision):

1. **Update the affected section(s)** in place (architecture, repo map, feature catalog, APIs,
   CLI, tech stack, evaluation, limitations, future work).
2. **Append a dated entry to section 21 (Context update log)** — one line: what changed and why.
3. **Keep claims verifiable.** Prefer concrete file paths (`backend/app/...`), flag names and
   numbers over prose. If you cite a metric, say which run/set it came from.
4. **Do not let it rot.** If you touch a file this document describes and the description is now
   wrong, fix the description in the same change.
5. **Keep it one file.** Deep detail belongs in `docs/*.md`; this file links to them and
   summarises. Target length: a thorough but readable reference, not a dump of the codebase.

> Convention for Claude/agents: treat "update the project context" as "edit this file + add a
> section-21 log line". The matching long-term memory is `project-context-file` (see `.claude`
> memory index).

---

## 1. What AegisAI is (one paragraph)

AegisAI is a **zero-trust security layer for autonomous AI agents**. LLM agents read untrusted
text (user messages, documents, web pages) while holding real capabilities (databases, email,
the web, code). Prompt injection turns that untrusted text into unauthorised actions. AegisAI
sits between the model and its capabilities: it **screens every channel the model reads**,
**decides every tool call at a deny-by-default gateway**, **holds high-impact actions for a
human**, and **redacts sensitive data on the way out**. It attacks itself continuously (red-team
lab) and maps the evidence to the **OWASP Top 10 for LLM Applications (2025)** and **MITRE ATLAS**.
It is both a *secure agent runtime we built* and a *security middleware any other agent can route
through* (SDK + REST gateway + CLI + proxy).

**Design principle (the thesis of the whole project):** *the model is not a security boundary.*
The brain **proposes**; the gateway **disposes**. Every guarantee holds even when the model obeys
an injected instruction perfectly.

### Project metadata
- **Title:** AegisAI — *A Trust-Aware Security Gateway for RAG-Powered Agentic AI*
- **Tagline:** "Trust the knowledge. Control the action."
- **Authors:** Kartik Ghansela (26082), Mudita Jain (26111) — B.Tech CSE, Semester VII, Batch 2023–2027
- **Institution:** Dronacharya College of Engineering, Gurugram · Dept. of CSE
- **Mentor:** Ms Vimmi Malhotra · **HOD:** Dr Ashima Mehta
- **Repo:** https://github.com/BeingMudita/AegisAI · default branch `main`
- **Scale (as of last update):** ~198 Python files, ~46 TS/TSX files, 38 backend test files,
  ~15 frontend pages, 41 commits (30 Sep 2026 → 9 Oct 2026).

---

## 2. The problem and why it matters

- LLM agents **ingest untrusted text** and **hold real power** at the same time.
- A model **cannot reliably separate data from instructions**, so it can be fooled perfectly —
  it therefore cannot be the security boundary.
- **Prompt injection is OWASP LLM01**, the single highest risk for LLM applications.
- As organisations put agents into production with real access, a reusable layer that *assumes
  the model will be compromised and still contains the blast radius* is of direct relevance.
- AegisAI's answer: move enforcement **outside** the model, deny by default, keep a human in the
  loop for high-impact actions, and **measure** the defence rather than claim it.

---

## 3. Threat model (summary)

- **Assets:** the tools/capabilities (DB, email, web, shell), the knowledge base, user data,
  trust state and the audit log.
- **Adversary:** untrusted text in any channel the model reads — direct user injection, poisoned
  documents (RAG), poisoned web pages, malicious tool output, obfuscated payloads.
- **Core guarantee set (13 invariants, tested in CI on both storage backends):** no tool runs
  except through the gateway; off-policy tools / globally-disabled tools / off-list domains are
  always refused; `requires_approval` tools run only after an admin approves and only if every
  check still passes; injected documents and tool output never reach the model; secrets never
  reach an answer; red-team runs never touch live trust or the audit log.
- Full detail: [`docs/threat-model.md`](docs/threat-model.md).

---

## 4. Architecture

### 4.1 Request lifecycle (the agent turn — LangGraph workflow)
```
USER/API (JWT · roles)
  → guard_input      (firewall · suspension)
  → retrieve         (guarded RAG · trust-scored)
  → plan ⇄ act       (Ollama brain or rule-based planner; every tool call → gateway)
  → respond          (spotlighting)
  → guard_output     (DLP · link stripping)
```
Every layer is audited and moves a single running trust score. Deny-by-default throughout.

### 4.2 Defence-in-depth layers
| Layer | Responsibility | Code |
|---|---|---|
| **Firewall** | Prompt-injection/jailbreak scoring on every channel (input, retrieved chunks, tool args, tool output). Normalises obfuscation (zero-width, bidi, homoglyphs, leetspeak, spaced letters, base64). ALLOW / FLAG (sanitise) / BLOCK. Signature rules + learned semantic classifier. | `backend/app/firewall/` |
| **Trust engine** | 0–1 scores for agents, sources, tools. Attacks cost trust fast; clean behaviour regains slowly. Per-user agent trust. Below floor (0.2) → suspended. | `backend/app/trust/` |
| **Policies & registry** | Per-agent allow/block lists, domain allow-lists, sensitive-data categories (deny by default); global tool registry with risk levels, kill switches, rate limits, `requires_approval`. | `backend/app/policies/` |
| **Tool gateway** | The only path to any tool: registry → policy → domain → argument firewall → trust → rate limit → outgoing DLP → approval → execute → output scan → DLP. Email/URL args must name exactly one allowed destination. | `backend/app/tools/` |
| **Human approval** | High-impact calls wait in a queue; approval claims atomically, re-checks every gate, expires after `APPROVAL_TTL_MINUTES`. | `backend/app/tools/`, `routes/approvals.py` |
| **Guarded RAG** | Chunk-level screening at ingestion (quarantine + penalise source) and again at retrieval (drop untrusted/degraded). | `backend/app/rag/` |
| **Output DLP** | Redacts secrets/PII, strips links. | `backend/app/firewall/` (DLP) |
| **Telemetry** | Every decision counted; every incident a structured security event; isolated logs for red-team runs. | `backend/app/telemetry/` |

### 4.3 The single SecurityEngine (composition rule)
All interaction kinds funnel into **one** `SecurityEngine`
(`backend/app/platform/protocol/engine.py`). Adapters/proxy only translate a framework's wire
format into a neutral **AegisEvent**; they **never** re-implement firewall/trust/gateway/DLP
logic. See §18 and [[integration-layer-no-duplicate-security]].

Deeper dives: [`docs/architecture.md`](docs/architecture.md), [`docs/threat-model.md`](docs/threat-model.md).

---

## 5. Repository map

```
AegisAI/
├── backend/
│   ├── app/
│   │   ├── api/            # FastAPI app; api/routes/*.py per domain (see §8)
│   │   ├── agents/         # LangGraph runtime, brains (Ollama / rule-based), sessions
│   │   ├── auth/           # JWT auth, login limiter
│   │   ├── firewall/       # normalize.py, rules.py, scanner, DLP, semantic layer
│   │   ├── trust/          # engine.py, scoring.py (trust signals incl. BEHAVIORAL_ANOMALY)
│   │   ├── policies/       # per-agent policies, global tool registry, policy engine
│   │   ├── tools/          # sandboxed tools, zero-trust gateway, approval queue, sandbox
│   │   ├── rag/            # chunking, embeddings, guarded knowledge_base, seed corpus
│   │   ├── redteam/        # attack-suite runner + background run service
│   │   ├── compliance/     # catalog.py: OWASP LLM Top 10 / MITRE ATLAS + live evidence
│   │   ├── quotas/         # per-principal turn/token/cost budgets (LLM10)
│   │   ├── supply_chain/   # model provenance, SBOM/AI-BOM (LLM03)
│   │   ├── persistence/    # PostgreSQL implementations of every store
│   │   ├── telemetry/      # audit log (isolated red-team logs), logging
│   │   ├── database/       # models, sessions, migration entry point
│   │   └── platform/       # Developer platform + integration + DevSecOps + collective defence
│   │       ├── sdk.py           # SecureAgent, AegisGuard, AegisMiddleware
│   │       ├── gateway_api.py   # /v1/secure REST gateway
│   │       ├── cli.py           # `aegis` CLI
│   │       ├── policyfile.py    # aegis.yaml policy-as-code loader
│   │       ├── scanner.py       # agent audit → score/100 → least-privilege policy
│   │       ├── gate.py          # audit + red-team + threshold → PASS/FAIL (CI gate)
│   │       ├── registry.py      # connect→scan→protect onboarding
│   │       ├── adaptive.py      # runtime behaviour → posture NORMAL..QUARANTINED
│   │       ├── autopilot.py     # mines behaviour → policy recommendations (Simulate/Apply/Reject)
│   │       ├── threatintel.py   # cross-agent threat signatures (preemptive detection)
│   │       ├── attackgraph.py   # attack-surface graph, paths, blast radius, risk focus
│   │       ├── protocol/        # engine.py (the SecurityEngine), events.py, adapters.py, schemas.py
│   │       ├── adapters/        # base.py (registry), openai.py, mcp/ — framework translators
│   │       └── proxy/           # OpenAI-compatible drop-in proxy (router/server/transformer)
│   │   # aegisai/ (public SDK package: `from aegisai import SecureAgent`)
│   ├── migrations/         # Alembic revisions
│   ├── model-manifest.yaml # pinned model provenance (embedder commit+hashes, Ollama digests)
│   ├── data/               # inbox/ (drop files), uploads/, index/ (git-ignored)
│   └── tests/              # 38 test files incl. the red-team security gate (test_evaluation.py)
├── frontend/               # React 19 + Vite + Tailwind 4 + Recharts operator console (§7, §11)
├── attack-scenarios/       # red-team suites: 73 firewall cases, 21/22 agent scenarios, held-out sets
├── evaluation/             # CLI benchmark + report (run_eval.py)
├── docker/                 # Dockerfiles, nginx, compose
├── docs/                   # architecture, threat-model, platform, proxy, scanner, devsecops,
│                           #   threat-intelligence, supply-chain, operator-guide, archive-explorer
├── examples/external-agent/# demo: same agent exfiltrates on its own, blocked via the proxy
├── sample-data/            # ingest samples (3 hide injections)
├── render.yaml             # Render blueprint (API + database)
├── AegisAI_MidTerm2_Report.docx   # generated mid-term 2 report (14 pp)
├── AegisAI_Synopsis*.docx/.pptx   # synopsis + presentations
└── PROJECT_CONTEXT.md      # ← this file
```

---

## 6. Feature catalog

### 6.1 Core secure-agent runtime
Firewall, trust engine, policies + tool registry, zero-trust tool gateway, human approval,
guarded RAG, output DLP, telemetry — see §4.2.

### 6.2 Developer platform — plug your own agent in ([`docs/platform.md`](docs/platform.md))
- **Policy-as-code:** one `aegis.yaml` per agent (tools, domains, sensitive data, trust floor,
  human-approval) applied into the real policy/gateway stores.
- **SDK:** `SecureAgent` (whole pipeline), `AegisGuard` (firewall / tool pre-flight / output DLP
  primitives), `AegisMiddleware` (wrap any `Callable[[str], str]` agent).
- **REST gateway:** `POST /v1/secure/{chat,tool,scan}`, `GET /v1/secure/agents`; auth via
  `X-Aegis-Key` or JWT.
- **CLI:** `aegis init · scan · redteam · serve · inspect · audit · generate-policy · gate ·
  proxy · threats · blast · aibom · verify-models` (`python -m app.platform.cli`).

### 6.3 Security lifecycle — scan/generate/test/protect ([`docs/scanner.md`](docs/scanner.md))
`aegis audit` (score /100 + 7-category risk + fixes) → `aegis generate-policy` (least-privilege
`aegis.yaml`) → `aegis policy test` (red-team) → `aegis serve` / `aegis proxy` (protect).
Surfaces in the **Security scanner** dashboard page and `POST /v1/secure/audit`,`/generate-policy`.

### 6.4 Universal runtime integration layer ([`docs/proxy.md`](docs/proxy.md))
Take an existing agent, don't rewrite its security. Every framework (OpenAI, LangGraph, MCP,
custom) → neutral **Aegis event** → the one SecurityEngine → ALLOW / APPROVAL / BLOCK. The proxy
exposes a drop-in **OpenAI-compatible** `POST /v1/chat/completions` plus
`/v1/proxy/{tool,output,chat,mcp}`. `aegis proxy --config aegis-agent.yaml --port 9000`.

### 6.5 AI-DevSecOps — before/during/after deployment ([`docs/devsecops.md`](docs/devsecops.md))
- **Registry:** `connect→scan→protect` onboarding (`POST /api/registry/agents`→`/scan`→`/protect`).
- **Security gate:** audit + red-team + threshold → PASS/FAIL, exit-coded for CI
  (`aegis gate <agent> --threshold 90`, `POST /api/gate`).
- **GitHub Action:** the gate as a PR check (`.github/actions/aegis-security/`).
- **Runtime adaptive security:** observe behaviour → trust penalties (`BEHAVIORAL_ANOMALY`) →
  posture `NORMAL→SUSPICIOUS→RESTRICTED→QUARANTINED`; the proxy tightens enforcement per posture
  (`GET /api/adaptive/agents/{id}`).
- **Autopilot:** mines the gateway log + adaptive monitor's observed calls → policy
  recommendations a human can **Simulate / Apply / Reject** (never a silent edit).

### 6.6 Collective & structural defence ([`docs/threat-intelligence.md`](docs/threat-intelligence.md))
- **Threat Intelligence Engine:** learns normalised threat **signatures** (word-shingle
  fingerprints) from firewall FLAG/BLOCK + domain-refused exfil, shared across all agents. A HIGH
  match escalates a firewall-clean verdict (reason `known_attack_pattern`; Jaccard ≥ 0.6).
  `aegis threats`, `/api/threat-intel/*`.
- **Attack-surface analysis:** builds a graph from the scanner profile, enumerates dangerous
  **paths** (data_exfiltration, indirect_injection_to_exfil, privilege_escalation), scores
  **blast radius** 0–100, `compare_hardening()` shows least-privilege reduction, `risk_guided_focus()`
  ranks red-team families. `aegis blast <agent>`, `/api/attack-surface/*`.

### 6.7 Supply chain ([`docs/supply-chain.md`](docs/supply-chain.md)) — closes LLM03
Model provenance pins (embedder HF commit + SHA-256 of all 10 files; Ollama manifest digests;
`MODEL_PROVENANCE=enforce|warn|off`), CycloneDX SBOMs + AI-BOM (`aegis aibom`, `verify-models`),
Trivy image/Dockerfile scans, SHA-pinned CI actions, non-root `nginx-unprivileged` dashboard.

---

## 7. Technology stack
| Layer | Tech | Why |
|---|---|---|
| Presentation | React 19, TypeScript, Tailwind CSS 4, Recharts | Type-safe component console, accessible charts |
| API / middleware | Python 3.11, FastAPI, PyJWT | Async, typed, fast security middleware |
| Agent runtime | LangGraph, LangChain Core, Ollama | Deterministic graph; local model on-prem + rule-based fallback |
| Knowledge / RAG | custom RAG pipeline, pypdf, Sentence-Transformers (optional ML) | Full control of ingestion screening + chunk-level trust |
| Data | PostgreSQL 16, pgvector, SQLAlchemy, Alembic | Durable multi-worker state + vector search, versioned migrations |
| Platform | Docker, Docker Compose, GitHub Actions CI, Render, Vercel | Reproducible builds + CI security gate |

---

## 8. API surface (`backend/app/api/routes/`)
`agents`, `approvals`, `auth`, `sessions`, `retrieval`, `vectors`, `tools`, `policies`, `trust`,
`firewall`, `redteam`, `compliance`, `security_events`, `usage`, `scanner`, `gate`, `registry`,
`adaptive`, `autopilot`, `threatintel`, `attack_surface`, `supply_chain`.
Developer-platform gateway is separate: `/v1/secure/*` (`gateway_api.py`) and the proxy
`/v1/chat/completions` + `/v1/proxy/*` (`platform/proxy/`). Interactive docs at
`http://localhost:8000/docs`.

---

## 9. CLI (`aegis`, `python -m app.platform.cli`)
`init` · `scan` · `audit` · `generate-policy` · `policy test` · `redteam` · `gate` · `serve` ·
`proxy` · `inspect` · `threats` · `blast` · `aibom` · `verify-models`.

---

## 10. Data & storage
`STORAGE_BACKEND=memory` (default; single worker; KB optionally saved to `backend/data/index/`)
or `postgres` (`DATABASE_URL`: events, trust, sessions/turns, tool requests/approvals, red-team
runs, users, policies, pgvector KB, ingestion jobs, rate limits; durable + multi-worker).
Ingest via Knowledge base page (upload / `backend/data/inbox/` + import / paste); formats
`.txt .md .csv .tsv .json .jsonl .html .pdf .log`. Process-local vs shared: login limiter,
session exclusivity and request-ID replay protection are in-memory in memory mode, shared across
workers in postgres mode.

---

## 11. Frontend (operator console)
Vite + React 19 + Tailwind 4 + Recharts. **Single fixed light-airy theme** (white + sage/forest
green + grey; no light/dark toggle). Fonts: Cinzel (display/titles), Playfair Display (headings/
numbers), Inter (body). Animated plexus backdrop; isometric "knowledge landscape" viz.
Pages (`frontend/src/pages/`): Login, Overview, Events (Security events), Trust, KnowledgeBase,
Database, AgentConsole (Agent workspace), FirewallLab, Approvals, Sessions, RedTeam (Red-team
lab), ThreatCoverage, Architecture, Policies, Scanner, AttackReplay.
Design-system detail + conventions: memory [[ui-design-system]] and [`frontend/README.md`].

---

## 12. Build / run / test (quickstart)
```bash
# Backend
cd backend && python -m venv .venv && . .venv/Scripts/activate   # (Windows)
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload                 # http://localhost:8000/docs
# Frontend
cd frontend && npm install && npm run dev      # http://localhost:5173
# Dev logins (Vite dev server only): admin/admin123, analyst/analyst123, agent/agent123
# Full stack
docker compose -f docker/docker-compose.yml up --build            # dashboard :8080
# Tests & evaluation
cd backend && pytest -q                         # add AEGIS_TEST_POSTGRES=1 for pg + cross-worker
python ../evaluation/run_eval.py
```
Without Ollama the agents use the rule-based planner automatically.

---

## 13. Evaluation & results
| Metric | Development set (83) | Held-out v1+v2 (108) |
|---|---|---|
| Firewall precision / recall | **98.0% / 100%** (50/50 attacks) | **91.8% / 70.3%** (45/64) |
| False-positive rate | 3.0% (1/33 benign) | 9.1% (4/44 benign) |
| End-to-end agent scenarios | **22 / 22 defended** | — |
| Scan latency p95 | ~0.3 ms (in-process, CPU) | — |

Rules were tuned on the dev set and the semantic layer trained on it (optimistic); held-out sets
(`firewall_holdout.yaml`, `firewall_holdout_v2.yaml`) are never tuned on. Semantic layer (Phase
12) lifted held-out v2 recall 27%→61%; Phase 12.1 — intent-abstraction features
(`firewall/lexicon.py`) + deterministic adversarial augmentation (`firewall/adversarial.py`,
trains weights only, metrics still measured on real dev cases) — lifted it further to **82%** at
0% semantic false positives, honestly (a 5-gram leakage guard, `assert_disjoint_from`, keeps the
held-out set out of training). CI gate (`backend/tests/test_evaluation.py`) fails below
90% dev recall/precision, >10% FP, any benign blocked, or any scenario failing. See
[`evaluation/README.md`](evaluation/README.md) and [`attack-scenarios/README.md`](attack-scenarios/README.md).

---

## 14. Development history (phases 0–13)
| Phase | Delivered |
|---|---|
| 0 | Project scaffold |
| 1 | Backend foundation — API structure, config, JWT auth |
| 2 | Database & policy system |
| 3 | Firewall (prompt-injection detection, obfuscation handling, DLP) |
| 4 | Trust engine |
| 5 | Agents + RAG + tool gateway |
| 6 | Frontend dashboard |
| 7 | Attack scenarios & evaluation |
| 8 | Deployment (Docker, Render, Vercel, CI) |
| 9 | Durable PostgreSQL + pgvector: Alembic, transactional stores, cross-worker session locks, shared replay rejection + rate limits |
| 10 | Retention & quotas: audit retention, session expiry, keyset pagination, per-principal turn/token/cost budgets (closes LLM10) |
| 11 | Assurance: human approval workflow, red-team lab, OWASP/ATLAS threat coverage, threat model |
| 12 | Paraphrase dev set + learned semantic injection layer (held-out v2 recall 27→61%) |
| 12.1 | Generalisation: intent-abstraction features + adversarial augmentation (held-out v2 recall 61→82%, 0% semantic FP; no-leakage 5-gram guard) |
| 13 | Supply chain: CycloneDX SBOMs + AI-BOM, Trivy scans, SHA-pinned CI, model provenance (closes LLM03) |
| + | **Developer platform** (SDK, `/v1/secure`, CLI, `aegis.yaml`), **Scanner core**, **Aegis Event Protocol + integration proxy**, **Agent Registry / Runtime Adaptive Security / Autopilot / Security Gate / GitHub Action**, **Threat Intelligence Engine**, **Attack-surface/blast-radius** (added early–mid Oct 2026) |

---

## 15. Current state (what works today)
All core phases complete and tested on both storage backends. Implemented, tested and documented:
security engines (firewall, trust, policies/registry, gateway, approval, guarded RAG, DLP,
telemetry); LangGraph agent runtime with Ollama/rule-based brains; guarded knowledge base; the
~15-page operator console; the developer platform (SDK/REST/CLI/policy-as-code); the universal
integration proxy; the full AI-DevSecOps set (registry, gate, GitHub Action, adaptive, autopilot);
collective defence (threat intel, attack graph); supply-chain assurance. OWASP LLM01/02/03/05/06/
07/10 mitigated; the red-team lab verifies evidence live.

---

## 16. Known limitations & residual risk
- ~4 in 10 **paraphrased** attacks still bypass the firewall's signature rules → the
  **deny-by-default gateway, not the firewall, is the primary control**.
- Tools are **sandboxed simulations** (no real email/shell/network side effects yet).
- OWASP **LLM04 / LLM08 / LLM09 remain partial** (retrieval-only poisoning defence; no independent
  fact verification).
- In-memory backend resets on restart; durable multi-worker state needs PostgreSQL.
- No **organisation identity** (SSO/OIDC), tenant isolation, or per-user delegated permissions yet.

---

## 17. Future work / roadmap
- **Generalisation:** ✅ done in Phase 12.1 — intent-abstraction features + adversarial augmentation
  lifted held-out v2 recall to 82% (combined held-out 80%), from ~45%. Next: an *independent* held-out
  set from an outside red team (current held-out shares an author), and non-linear / embedding features.
- **Standards:** complete OWASP LLM Top 10 + broaden MITRE ATLAS, with automated residual-risk reports.
- **Multi-agent & tools:** policy-aware gateway for multi-agent workflows; expanded tool/plugin registry.
- **Production hardening:** managed deployment, SIEM/observability export, verified performance under load.
- **Autonomous red-teaming:** risk-guided fuzzing feeding new signatures back into the firewall.
- **Model-agnostic brains:** pluggable local + hosted LLM backends with per-model trust calibration.
- **Identity:** SSO/OIDC, tenant isolation, per-user delegated permissions, real tool adapters behind approval.

---

## 18. Design rules & gotchas (hard constraints — do not violate)
- **One security core, many thin adapters.** Adapters/proxy must **never** duplicate firewall/
  trust/gateway/DLP logic — they only translate wire format → `AegisEvent` → `SecurityEngine`
  (`platform/protocol/engine.py`). New framework = new `AgentAdapter` in `platform/adapters/`
  (register in `base.py`); new interaction kind = new event type + a branch in `evaluate`.
  (memory: [[integration-layer-no-duplicate-security]])
- **Threat intel runs before the verdict is recorded.** `intel.match()` is called on INPUT/
  RETRIEVAL/TOOL_RESULT/OUTPUT **before** `record_verdict()`, so a signature can't match its own
  record. `ThreatSignature.fingerprint` is a `frozenset` with `exclude=True` so it serialises out
  of API responses. (memory: [[threat-intel-and-attack-graph]])
- **Autopilot reads two sources.** The proxy uses the gateway's dry-run `authorize()` which does
  **not** persist to the request log, so Autopilot also mines the adaptive monitor's `recent_events`.
- **Scanner treats `domains.allowed: ["*"]` as unlocked (HIGH)** so the gate catches that weakening.
- **Gateway charges trust to the calling principal**, and compares its API key in constant time.
- **Red-team runs are isolated** — never touch live trust scores or the audit log.
- **UI is a single fixed light theme** — no dark mode; keep every page consistent (memory:
  [[ui-design-system]]).
- **With `ENVIRONMENT=production`** the API refuses to start while `JWT_SECRET` or any
  `SEED_*_PASSWORD` is still default. Never commit `.env`/secrets.

---

## 19. Documentation index
| Doc | For |
|---|---|
| [`README.md`](README.md) | Public overview, quick start, threat coverage, evaluation |
| [`docs/architecture.md`](docs/architecture.md) | Request lifecycle, gateway, approvals, data stores, cross-worker guarantees |
| [`docs/threat-model.md`](docs/threat-model.md) | Assets, boundaries, adversaries, threats, guarantees, residual risk |
| [`docs/platform.md`](docs/platform.md) | SDK, `/v1/secure` gateway, CLI, `aegis.yaml` |
| [`docs/scanner.md`](docs/scanner.md) | Audit → score/100 → least-privilege policy → red-team |
| [`docs/proxy.md`](docs/proxy.md) | Event protocol, adapters, the proxy, `aegis proxy` |
| [`docs/devsecops.md`](docs/devsecops.md) | Registry, gate, GitHub Action, adaptive security, autopilot |
| [`docs/threat-intelligence.md`](docs/threat-intelligence.md) | Cross-agent signatures, attack graph, blast radius |
| [`docs/supply-chain.md`](docs/supply-chain.md) | Model provenance, SBOM/AI-BOM, image scanning |
| [`docs/operator-guide.md`](docs/operator-guide.md) | Review workflow and deployment boundaries |
| [`CHANGELOG.md`](CHANGELOG.md) | What changed, with validation results |
| [`SECURITY.md`](SECURITY.md) | Vulnerability reporting + hardening checklist |

---

## 20. Deliverables & artifacts
- `AegisAI_MidTerm2_Report.docx` — 14-page Mid-Term 2 report (abstract, index, 6 chapters,
  diagrams from the deck, live screenshots, 10 numbered tables; Times New Roman 12, double-spaced, A4).
- `AegisAI_Synopsis.docx`, `AegisAI_Presentation.pptx`, `AegisAI_Synopsis_Presentation.pptx`
  (synopsis + decks; the deck is the source for the architecture diagrams used in the report).
- `logo_dronacharya.jpeg` — institution logo used on report/deck.

---

## 21. Context update log (append newest at top)
| Date | Change |
|---|---|
| 2026-10-10 | **Phase 12.1 — semantic-firewall generalisation.** Added intent-abstraction features (`backend/app/firewall/lexicon.py`, `semantic_features.py`; `FEATURE_VERSION`→2) and deterministic adversarial augmentation (`backend/app/firewall/adversarial.py`, trains weights only; threshold/metrics on real dev cases via `out_of_fold_probabilities(extra=…)`). Honest held-out v2 recall 61%→82% at 0% semantic FP; combined held-out ~80%. Enforced a no-test-leakage 5-gram guard (`assert_disjoint_from`, `tests/test_adversarial.py`) after catching held-out phrasings in an early draft. Retrained `semantic_model.json`; docs updated (CHANGELOG, evaluation/README). |
| 2026-10-10 | **Created this file.** Captured full project context to end of Phase 13 + the platform/integration/DevSecOps/threat-intel/attack-graph additions. Also generated the 14-page Mid-Term 2 report (`AegisAI_MidTerm2_Report.docx`). |

<!-- Add a new row above for each significant change. See the MAINTENANCE PROTOCOL in §0. -->

# AegisAI Architecture

> Living document — expanded as phases are implemented.

## Overview

AegisAI is a zero-trust security layer positioned between untrusted input and
an autonomous agent's ability to act. Every inbound message, retrieved
document, and requested tool call passes through defensive checkpoints, and
nothing an LLM proposes is trusted: the brain *proposes*, the gateway *disposes*.

## Request lifecycle

One agent turn is a LangGraph workflow (`app/agents/runtime.py`):

```
START → guard_input ─┬─ blocked ───────────────────────────────▶ END (refusal)
                     └→ retrieve → plan ─┬─ tool → act ─┐
                                    ▲    │              │  ≤ AGENT_MAX_STEPS
                                    │    └──────────────┘
                                    │    └─ answer → respond → guard_output → END
```

| Node | Checks |
|------|--------|
| `guard_input` | Agent not suspended (trust ≥ 0.2) · firewall on the user message (BLOCK ends the turn and costs trust; FLAG is audited and costs a little trust) |
| `retrieve` | Policy must allow `search_documents` and trust must meet its bar · guarded RAG retrieval |
| `plan` | The brain (Ollama or rule-based) proposes one tool call or to answer |
| `act` | The tool gateway runs every checkpoint below |
| `respond` | The brain writes the answer; retrieved / tool text is wrapped in `<data>` tags and declared non-executable (spotlighting) |
| `guard_output` | DLP (secrets always; PII when the agent has sensitive-data categories) · exfiltration-link removal |

### Tool gateway (`app/tools/gateway.py`)

Checks run cheapest-first; the first failure denies the call.

1. **registry** — tool exists in `default_policies.yaml` and isn't globally disabled
2. **policy** — agent policy allows it (deny by default; block-list wins)
3. **domain** — URL / email arguments are on the agent's domain allow-list (subdomains included)
4. **firewall** — arguments scanned on the `TOOL_ARGUMENTS` channel
5. **trust** — agent trust ≥ the tool's `min_trust` (else risk-level default, else `TRUST_THRESHOLD`)
6. **rate_limit** — per agent and tool, sliding 60-second window

Then the tool runs (sandboxed simulations — no real shell, network or email),
its **output** is scanned on the `TOOL_OUTPUT` channel (BLOCK withholds it and
penalizes the source), and **DLP** redacts PII when the tool's data category is
sensitive for the agent. Every outcome is audited and moves the agent's trust.

## Component map

| Package | Role |
|---------|------|
| `app/api` | FastAPI routes: auth, firewall, agents, sessions, retrieval, trust, tools, policies, security-events |
| `app/firewall` | `normalize.py` (de-obfuscation), `rules.py` (weighted signatures), `scanner.py` (noisy-OR scoring, sanitize, audit), `dlp.py` |
| `app/trust` | `scoring.py` (pure math), `engine.py` (registry, history, gating) |
| `app/policies` | `engine.py` (per-agent decisions), `store.py` (agent policies), `config.py` (global registry & RAG rules) |
| `app/agents` | `runtime.py` (LangGraph), `brain.py` (Ollama / rule-based), `sessions.py` |
| `app/rag` | `chunking.py`, `embeddings.py`, `store.py`, `knowledge_base.py`, `seed/` demo corpus |
| `app/tools` | `sandbox.py` (simulated tools), `gateway.py` |
| `app/telemetry` | `store.py` (audit log), `logging.py` (structlog setup) |
| `app/database` | Models, sessions, migrations |

## Firewall scoring

Text is normalized (NFKC, invisible/bidi characters stripped, Cyrillic/Greek
homoglyphs mapped, whitespace collapsed); de-leeted and de-spaced variants and
decoded base64 payloads are scanned too. Each matching rule contributes a
weight *w*, combined as a noisy-OR:

    score = 1 − Π (1 − wᵢ)

`score ≥ FIREWALL_BLOCK_THRESHOLD` (0.8) → BLOCK; `≥ FIREWALL_FLAG_THRESHOLD`
(0.4) → FLAG. Rules carry a higher `indirect_weight` for the `RETRIEVED` and
`TOOL_OUTPUT` channels: text arriving as *data* should never address the model.

## Trust

Scores live in [0, 1] and map to levels UNTRUSTED < 0.2 ≤ LOW < 0.4 ≤ MEDIUM
< 0.6 ≤ HIGH < 0.85 ≤ VERIFIED. Penalties subtract their full magnitude
(firewall block −0.15, policy violation −0.10, injected content −0.20 …);
rewards are scaled by the headroom `(1 − score)`, so trust is lost quickly and
regained slowly. A drop to a lower level raises a `TRUST_DEGRADATION` event.
Agents start at 0.75; sources start from their declared trust level.

## Data stores

- **PostgreSQL + pgvector** — the schema below is defined and is the intended
  source of truth. Today the runtime keeps state in in-memory stores that
  mirror these tables (policy store, audit log, trust registry, sessions,
  tool-request log, vector index); each sits behind one class, so moving to
  the database changes the store, not its callers.

### Schema (Phase 2)

| Group | Tables |
|-------|--------|
| Identity & governance | `users`, `agents`, `policies`, `agent_sessions` |
| RAG knowledge base | `document_sources`, `documents`, `document_chunks`, `embeddings` |
| Security | `trust_assessments`, `tool_definitions`, `tool_requests`, `security_events` |

Models live in `app/database/models/`; `embeddings.vector` is a pgvector
`Vector(EMBEDDING_DIM)` column. Bootstrap locally with:

```bash
cd backend
python -m app.database.init_db   # enables pgvector + creates tables
```

## Policy engine

`app/policies/engine.py` answers *"what is this agent allowed to do?"* over an
`AgentPolicy` document (deny-by-default for tools; block-list wins over
allow-list; domain matching includes subdomains). Agent policies are loaded
from `app/policies/examples/*.json` via `app/policies/store.py`; the global
tool registry and RAG rules come from `app/policies/default_policies.yaml` via
`app/policies/config.py`. A tool must pass **both** layers.

## Production safeguards

- The API refuses to start with `ENVIRONMENT=production` while `JWT_SECRET`
  or any `SEED_*_PASSWORD` is a development default, and disables debug
  tracebacks.
- Logging cannot fail a request (unencodable characters are degraded).
- The dashboard renders agent output as React elements — no raw HTML.
- The container runs as an unprivileged user; nginx sends CSP and
  anti-framing headers.

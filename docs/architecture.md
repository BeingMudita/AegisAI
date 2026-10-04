# AegisAI Architecture

> Living document — expanded as phases are implemented. For adversaries, trust
> boundaries and residual risk see the [threat model](threat-model.md).

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
7. **approval** — tools marked `requires_approval` stop here as `PENDING`
   (see [Human approval](#human-approval)); everything else continues

Then the tool runs (sandboxed simulations — no real shell, network or email),
its **output** is scanned on the `TOOL_OUTPUT` channel (BLOCK withholds it and
penalizes the source), and **DLP** redacts PII when the tool's data category is
sensitive for the agent. Every outcome is audited and moves the agent's trust.

## Component map

| Package | Role |
|---------|------|
| `app/api` | FastAPI routes: auth, firewall, agents, sessions, retrieval, trust, tools, policies, security-events, approvals, redteam, compliance |
| `app/firewall` | `normalize.py` (de-obfuscation), `rules.py` (weighted signatures), `scanner.py` (noisy-OR scoring, sanitize, audit), `dlp.py` |
| `app/trust` | `scoring.py` (pure math), `engine.py` (registry, history, gating) |
| `app/policies` | `engine.py` (per-agent decisions), `store.py` (agent policies), `config.py` (global registry & RAG rules) |
| `app/agents` | `runtime.py` (LangGraph), `brain.py` (Ollama / rule-based), `sessions.py` |
| `app/rag` | `chunking.py`, `embeddings.py`, `store.py`, `knowledge_base.py`, `seed/` demo corpus |
| `app/tools` | `sandbox.py` (simulated tools), `gateway.py` (checkpoints and the approval queue) |
| `app/telemetry` | `store.py` (audit log, with a context-local override for isolated runs), `logging.py` (structlog setup) |
| `app/redteam` | `runner.py` (firewall benchmark, agent scenarios in fresh runtimes), `service.py` (background runs, history) |
| `app/compliance` | `catalog.py` (controls, OWASP LLM Top 10 2025, MITRE ATLAS), `service.py` (live evidence) |
| `app/persistence` | PostgreSQL implementations of every store |
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

Every operational store sits behind one interface with two implementations,
chosen by `STORAGE_BACKEND`:

| Store | `memory` | `postgres` (`app/persistence/`) |
|---|---|---|
| Audit log | bounded deque | `security_events`, `decision_counters` (atomic upserts); not erasable via the API |
| Trust | dict + lock | `trust_scores` (row lock per update) + `trust_assessments` history |
| Sessions | dict + lock | `agent_sessions`, `session_runs`, `agent_turns` |
| Tool gateway log / limits / approvals | deque + per-process windows | `tool_requests` (incl. review columns) + `rate_limit_hits` |
| Red-team runs | last 25 in memory | `redteam_runs` (JSON payload per run) |
| Login throttle | per-process buckets | `rate_limit_hits` |
| Users, policies | seeded in memory / JSON files | `users`, `agents`, `policies`, `tool_definitions` (seeded once) |
| Knowledge base | in-memory index (+ optional disk save) | `document_sources` → `documents` → `document_chunks` → `embeddings` (pgvector, HNSW cosine index) |
| Ingestion jobs | per process | `ingest_jobs` (any worker can list or cancel) |

### Cross-worker guarantees (Postgres)

- **One turn per session at a time.** `begin_turn` locks the session row and
  refuses while a `session_runs` row is `running` with an unexpired lease.
  Progress reports extend the lease (`SESSION_LEASE_SECONDS`), so a crashed
  worker's lock expires instead of blocking the session forever.
- **Replay rejection.** A unique `(session_id, request_id)` constraint rejects a
  repeated request ID on any worker, permanently, including failed attempts.
- **No lost trust updates.** Each change is a read-modify-write under
  `SELECT … FOR UPDATE`, recorded with its previous score.
- **Exact shared limits.** Rate-limit attempts take a transaction-scoped
  advisory lock per key before counting the rolling window.
- **Seed once.** Reference data and the demo corpus are seeded under advisory
  locks, so workers starting together don't duplicate them.
- **Consistent vectors.** Search compares only embeddings made by the current
  model (`embeddings.model`), so changing `EMBEDDING_BACKEND` never mixes spaces.

Audit-style tables store agent and session identifiers as text rather than
foreign keys: audit records must outlive the rows they describe.

### Migrations

The schema is managed with Alembic (`backend/migrations/`). Apply it with:

```bash
cd backend
python -m app.database.migrate --seed   # upgrade to head, then seed reference data
```

The Docker image runs this before starting uvicorn when `STORAGE_BACKEND=postgres`.
`tests/test_postgres.py::test_migrations_match_models` fails if the models and
migrations ever drift apart.

## Human approval

A tool with `requires_approval: true` in `default_policies.yaml` (today: `send_email`)
is never executed by the agent turn that asks for it. After all six automatic
checks pass, the gateway records the request as `PENDING` with an expiry
(`APPROVAL_TTL_MINUTES`, 60 by default) and the agent tells the user it is waiting.

```
PENDING ──approve──▶ APPROVED (claimed) ──re-check ok──▶ EXECUTED
   │                                     └─re-check fails─▶ DENIED
   ├──reject──▶ DENIED  (agent trust −, TOOL_DENIED event)
   └──TTL────▶ DENIED  ("No decision before the approval request expired.")
```

- **Exactly once.** Approval first *claims* the request: a compare-and-set from
  `PENDING` to `APPROVED` under a lock (memory) or one
  `UPDATE … WHERE status = 'PENDING' RETURNING` (Postgres). A second approver, or
  a second worker, gets 409 and the tool never runs twice.
- **Re-checked at decision time.** The claimed request runs every checkpoint
  again. If the agent's trust fell, its policy changed or the domain left the
  allow-list since it was queued, the approval ends in `DENIED` with the failing
  check recorded.
- **Accountable.** `reviewed_by`, `review_note` and `reviewed_at` are stored on the
  request and the decision is audited as a security event.
- **Access.** `GET /api/approvals` is open to staff; approve and reject
  (`POST /api/approvals/{id}/approve|reject`) are admin-only.

## Red-team lab

`POST /api/redteam/runs` (staff) starts a background run of the suites in
`attack-scenarios/`: the 73-case firewall benchmark and the 21 agent scenarios.
Only one run executes at a time (409 otherwise; a run still marked running after 15 minutes is
treated as stale).

Runs are sandboxed from live state:

- `isolated_audit_log()` swaps the audit log for the duration of the run through a
  `ContextVar`, so attack traffic never reaches Security events or the counters.
- Each agent scenario builds a fresh trust engine, tool gateway and knowledge base.

Progress is saved at most every 0.25 s. Finished runs (precision, recall, F1,
per-family detection, confusion matrix, latency, every case and scenario) are kept
in memory or in `redteam_runs`. `evaluation/run_eval.py` and the CI gate use the
same runner.

## Threat coverage

`app/compliance/catalog.py` is a reviewed, code-maintained mapping of 16 controls to
the OWASP Top 10 for LLM Applications 2025 and nine MITRE ATLAS techniques. Each
threat has a status (mitigated / partial / gap), the controls that address it, the
evidence that should prove it, and a residual-risk statement.

`GET /api/compliance` resolves the evidence against the latest completed red-team run:

- `category:` refs pass at ≥ 90% detection; below that they are *weak*.
- `scenario:` refs pass when the scenario was defended.
- `test:` refs point at CI tests.

A threat is *verified* only when all of its run-based evidence passes. The catalog
states the project's claims; the run checks them. `tests/test_compliance.py` keeps
every reference valid.

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
- API responses disable caching and include nosniff, anti-framing, and no-referrer
  headers. Login hashing runs in a worker thread rather than blocking the event loop.
- A bounded rolling-window limiter reserves login attempts atomically: ten per
  ASGI peer per minute, with Retry-After on rejection. Unknown usernames still
  run a password check against a dummy hash to reduce timing differences.

## Observable execution and session coordination

`AgentRuntime._observed` wraps the existing graph nodes with an optional per-turn
callback. It publishes a running state before work starts and a terminal stage
status after completion. The graph and gateway remain the execution authority.
Progress does not include unfinished answers, tool arguments, or exception text.
Planning now records a trace even when no tool is needed or the tool limit is reached.

The synchronous message endpoint reserves the session under `SessionStore`'s lock
before invoking the graph. It appends the completed turn and finalizes progress in
`finally`, releasing the session on either success or failure. Overlapping turns,
closing during execution, and previously attempted request UUIDs return HTTP 409.
The optional `MessageRequest.request_id` UUID is generated for legacy callers that
omit it; clients that want replay protection must reuse their original UUID.

`GET /api/sessions/{id}/progress` returns null before the first run, then the latest
run's identifier, running/completed/blocked/failed status, current stage, stage
statuses, and timestamps. It uses the same owner/staff checks as session reads.
The console polls every 400 ms while a send is pending and matches the request ID
to prevent a previous run's progress from appearing as current. After completion,
the guarded turn's trace remains the primary evidence. Fast runs can finish between
polls; the UI does not insert artificial delays or invent progress percentages.

In memory mode this coordination is process-local, so use a single worker. With
`STORAGE_BACKEND=postgres` the same guarantees hold across workers (see
[Cross-worker guarantees](#cross-worker-guarantees-postgres)).

## Workspace structure

The overview introduces prepare → run → review, then operational metrics and
drill-down analytics. Pages are lazy-loaded and have a recoverable rendering error
boundary. The shared API hook cancels requests on unmount/path change, prevents
overlapping polling, pauses interval requests while the tab is hidden, and times
out reads after 15 seconds. Mutation requests are not automatically retried.

The interactive architecture map is a code-maintained description of these
components, not service discovery or a live deployment health map. Its connections
include the agent/tool loop, retrieval context, policy authorization, and audit
events. Keep `frontend/src/pages/Architecture.tsx` aligned with runtime changes.

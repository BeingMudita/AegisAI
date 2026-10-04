# Changelog

## 2026-10-04 — Code review fixes: security, correctness, performance, supply chain

### What changed

**Security**

- **Direct tool calls are ADMIN only.** `POST /api/tools/execute` let any signed-in
  user act as any agent (and earn trust on its behalf). Everyone else goes through
  agent sessions.
- **One destination per email or URL argument.** The domain check read only the text
  after the last `@`, so `attacker@evil.io, cfo@company.com` passed as `company.com`.
  Email arguments must now be one plain address; URLs must be a single `https` URL
  with no credentials, backslashes or spaces. Anything ambiguous is denied.
- **Trust is scoped to the principal.** Signals from a turn are charged to
  `FinanceAgent@<user>`; every gate uses the lower of that and the agent's baseline.
  One user's attacks can no longer suspend a shared agent for everyone. The baseline
  moves only by admin override or unattended runs. `/api/agents` reports the trust
  that gates the agent for the caller; the Trust page shows “FinanceAgent · for admin”.
  Tool requests record `requested_by`, and approval re-checks against it.
- **Spotlighting can't be escaped.** Text inside `<data>` blocks is HTML-escaped, so a
  document containing `</data>` can no longer close the block early.
- **Login throttling** adds a per-account limit (20 failures / 15 min) next to the
  per-address one, and disabled accounts get no token. The Docker image sets
  `FORWARDED_ALLOW_IPS` (private networks) so the throttle sees real client
  addresses behind a proxy, and nginx replaces any client-supplied `X-Forwarded-For`.
- **PyJWT replaces python-jose** (unmaintained, with published CVEs); `exp` and `sub`
  are now required claims.
- **DLP on outgoing tool arguments.** Email subjects and bodies and upload payloads
  are redacted before the call is queued or run (secrets always, PII for agents with
  sensitive data), so neither the recipient nor the stored request sees them.

**Bugs**

- nginx accepts uploads up to 1024 MB (it defaulted to 1 MB) and streams them.
- `sanitize()` cuts injection spans out of the *original* text, so line breaks,
  tables and Cyrillic/Greek text survive; leetspeak, spaced-out and base64 matches
  are removed too (they used to stay), and invisible characters are stripped.
- A non-object JSON reply from Ollama no longer fails the turn with a 500; every LLM
  error falls back to the rule-based planner.
- Turns have a wall-clock budget (`AGENT_TURN_TIMEOUT`, 150 s; nginx waits 200 s).
- Chunks default to 180 words (was 512): all-MiniLM-L6-v2 reads about 190 words and
  silently dropped the rest.
- Red-team runs give the tools the sandbox's own knowledge base and outbox.
- `tool_definitions` mirrors the policy file (it was seeded with
  `requires_approval=false` for every tool).

**Performance (Postgres mode)**

- Route handlers that reach a store, and `get_current_user`, are plain `def`, so
  database calls no longer block the event loop.
- Progress polling checks session ownership without loading every turn.
- Decision counters are buffered per worker (one upsert at most every 2 s, before a
  summary and at shutdown); trust reads are a plain SELECT when the row exists;
  policies are cached for `POLICY_CACHE_SECONDS` (5 s).
- New `GET /api/approvals/pending-count` for the navigation badge; the approval queue
  no longer loads 500 rows; the jobs list polls every 5 s unless something is
  ingesting; changing a poll interval no longer blanks the data.
- Migration `0004`: `tool_requests.requested_by`, `lower(...)` indexes for the
  case-insensitive lookups, and a `(key, at)` index on `rate_limit_hits`. Rate-limit
  hits older than an hour are swept; `redteam_runs` keeps the newest 25.

**Code health and supply chain**

- Removed the unused async engine (`database/session.py`, `init_db.py`) and the
  `asyncpg` dependency, `require_any`, `check_sensitive` and `add_turn`.
  `POST /api/policies` answers 501 (not 201 "not_implemented").
- `DEBUG` defaults to false. The backend image has no compiler or headers. Dev ports
  in compose bind to localhost. The Ollama image is pinned.
- `backend/requirements.lock` pins and hashes every runtime package; the image and CI
  install from it. CI adds `mypy` (now clean), `pip-audit` and `npm audit`;
  Dependabot is configured. The audit found 12 advisories in Starlette 0.48, so
  FastAPI moves to 0.142 and Starlette to 1.7.
- Re-uploading content that is already indexed (same SHA-256) completes at once as
  “Already indexed”; pasting duplicate text returns 409.

**Evaluation**

- New held-out firewall set, `attack-scenarios/firewall_holdout.yaml` (53 cases,
  never used for tuning), scored with every firewall run and shown in the Red-team
  lab and the report. On it the firewall scores precision 87.5%, recall 45.2%,
  false-positive rate 9.1% (development set: 97.6% / 95.3% / 3.3%). It catches every
  obfuscated, delimiter and tool-abuse case and none of the paraphrased ones.
- Threat coverage: LLM03 Supply Chain moves from gap to partial (new DEPENDENCIES
  control: 17 controls).

### Validation

- Memory mode: 182 passed, 11 skipped. Postgres mode (`AEGIS_TEST_POSTGRES=1`): 193 passed.
- New tests cover ambiguous destinations, outgoing DLP, per-principal trust (unit and
  end to end), sandbox isolation, sanitize formatting and obfuscated spans, per-account
  throttling, disabled accounts, duplicates, the pending-count endpoint, Ollama
  fallbacks and the turn budget, spotlight escaping, and the held-out set staying
  disjoint from the development set.
- Ruff, mypy, `pip-audit` (no known vulnerabilities) and `npm audit` pass; the
  frontend type-checks and builds.
- Evaluation: 21 / 21 agent scenarios; numbers above.

## 2026-10-03 — Assurance: human approval, red-team lab, threat coverage

### What changed

- **Human approval workflow.** Tools can be marked `requires_approval` in
  `default_policies.yaml`; `send_email` now is (and its trust bar moved from 0.80
  to 0.70, since a human now reviews every email). Such a call passes all six
  automatic checks, then waits as `PENDING` with an expiry (`APPROVAL_TTL_MINUTES`,
  default 60).
  - Admins approve or reject it with an optional note.
  - Approval claims the request atomically, so it never runs twice, even across
    workers.
  - Approval re-runs every check before executing.
  - Rejection costs the agent trust.
  - New API: `GET /api/approvals`, `POST /api/approvals/{id}/approve|reject`.
  - New dashboard page **Approvals**, with a live sidebar badge.
  - The agent's answer says what is waiting for approval.
- **Red-team lab.** Staff can launch the attack suites from the dashboard
  (`/api/redteam/runs`).
  - Runs execute in the background against an isolated audit log and fresh trust
    registries, so live state is untouched.
  - The page shows: detection KPIs, detection by attack family, a confusion
    matrix, a filterable case explorer (misses and false alarms), agent scenario
    outcomes, run history and JSON export.
  - `evaluation/run_eval.py` is now a thin CLI over the same runner (`app/redteam/`).
- **Threat coverage.** `app/compliance/catalog.py` maps 16 controls to the OWASP
  Top 10 for LLM Applications 2025 and nine MITRE ATLAS techniques.
  - Each threat has a status, controls, evidence and residual risk.
  - `GET /api/compliance` checks the evidence live against the latest red-team run.
  - New dashboard page **Threat coverage**: coverage matrix, threat detail, and
    code paths per control.
  - Current OWASP standing: 5 mitigated, 4 partial, 1 gap (LLM03 Supply Chain).
- **Documentation.**
  - Rewritten README.
  - New `docs/threat-model.md` and `SECURITY.md`.
  - New screenshots.
  - Updated architecture, operator, evaluation and manual-test guides.
- Navigation is grouped as Monitor / Operate / Assure / Govern. Policies & tools
  shows which tools need human approval.
- Migration `0003`: review columns on `tool_requests` (`expires_at`, `reviewed_by`,
  `review_note`, `reviewed_at`) and a `redteam_runs` table.
- The backend image now contains `attack-scenarios/`, so the Red-team lab works in
  Docker. New setting `REDTEAM_SUITES_DIR` overrides the location.

### Scenario changes

- AG-06 now expects the internal email to be **pending** approval, not sent.
- AG-21 starts FinanceAgent at trust 0.65 and expects `send_email` to be denied
  at the trust check.
- `test_trust_gate_and_admin_elevation` became `test_trust_gate_blocks_high_risk_tool`;
  approval itself is covered by `tests/test_approvals.py`.

### Validation

- Memory mode: 161 passed (11 Postgres-only tests skipped).
- Postgres mode (`AEGIS_TEST_POSTGRES=1`): 172 passed.
- New tests:
  - `test_approvals.py`: queueing, approve, reject, re-check failure, expiry,
    double-approval, role checks, API.
  - `test_redteam.py`: isolation from live state, report contents, API lifecycle,
    conflict handling.
  - `test_compliance.py`: catalog integrity and live evidence.
- Evaluation: precision 97.6%, recall 95.3%, false-positive rate 3.3%, agent
  scenarios 21 / 21.
- Ruff and the TypeScript build pass. The three new pages were exercised in a
  headless browser with no console errors: an email was queued, approved and
  executed, a red-team run completed, and coverage updated.

## 2026-10-03 — Phase 9: durable PostgreSQL + pgvector storage

### What changed

- New `STORAGE_BACKEND` setting. `memory` (default) keeps today's behaviour;
  `postgres` moves every operational store into `DATABASE_URL`: audit events and
  decision counters, trust scores and history, sessions with runs and turns, tool
  requests, users, agent policies, tool definitions, ingestion jobs, rate limits and
  the knowledge base (pgvector with an HNSW cosine index).
- Each store keeps its public interface; routes, the LangGraph runtime and the tool
  gateway are unchanged. Postgres versions live in `backend/app/persistence/`.
- Cross-worker guarantees: per-session execution locks with expiring leases,
  permanent request-ID replay rejection via a unique constraint, row-locked trust
  updates, advisory-locked shared rate limits (tool calls and logins), lock-protected
  seeding, and job progress/cancellation visible from any worker.
- The durable audit log refuses `DELETE /api/security-events` (409); only the
  coming retention policy may prune it.
- Alembic migrations (`backend/migrations/`, revisions 0001–0002) and
  `python -m app.database.migrate [--seed]`. Schema adjustments before first release:
  trust subjects and audit session/agent identifiers are text; new tables
  `trust_scores`, `decision_counters`, `session_runs`, `agent_turns`,
  `ingest_jobs`, `rate_limit_hits`.
- The Docker image migrates and seeds on start in Postgres mode and honours
  `WEB_CONCURRENCY`; compose runs two workers on Postgres; the Render blueprint
  provisions a database; CI gains a job running the suite on `pgvector/pgvector:pg16`.

### Validation

- Memory mode: 144 passed (11 Postgres-only tests skipped).
- Postgres mode (`AEGIS_TEST_POSTGRES=1`, embedded PostgreSQL 16.2 + pgvector 0.6.2):
  155 passed: the full existing suite plus 11 cross-worker tests (exclusive turns,
  replay rejection, lease expiry, progress visibility, 40 concurrent trust updates
  with none lost, shared tool and login limits, non-erasable audit log, pgvector
  retrieval and quarantine, cross-worker job cancellation, models match migrations).
- Migrations: upgrade, downgrade, upgrade clean; autogenerate reports no drift.
- End to end: two uvicorn workers on one database served a grounded answer, rejected
  a repeated request ID (409), blocked an injection, returned consistent session reads
  from both workers, seeded the demo corpus exactly once, and kept the conversation
  and trust score across a restart.
- Ruff passed. Formatting also reflowed whitespace in `app/agents/runtime.py` and
  `app/api/routes/sessions.py` (no logic changes).

### Remaining limits

Session histories and the audit log are not yet pruned; ingestion jobs are processed
by the worker that received the file (other workers can see and cancel them); the
pgvector extension must be available on the target database.

## 2026-10-02 — Observable security workspace

### Intent and preserved behavior

Read the project README and traced the API, LangGraph runtime, policy/trust gateway,
RAG ingestion, authentication, frontend, and existing tests before implementation.
Kept the existing agent brains, security decisions, sandboxed tools, document
processing, retrieval, and role/ownership checks. No database migration or external
tool integration is claimed in this update.

### Interface and usability

- Replaced the gradient-heavy presentation with a restrained teal/neutral palette,
  white navigation, flatter cards, readable secondary text, and consistent focus styles.
- Rebuilt sign-in with clear credential labels, disabled submission states, and an
  editorial layout. Development account shortcuts only exist in development builds.
- Reworked Overview around a practical prepare → run → review workflow with links
  into each step, role-aware metrics, agent readiness, recent incidents, and
  explicit deployment context. Retained detailed type/severity/trust analytics
  behind a disclosure and retained chart/table alternatives.
- Renamed the navigation labels to Knowledge base and Agent workspace for clarity.
- Added an interactive Architecture page with eight selectable components, SVG
  connections, highlighted data flows, a component inspector, implementation file
  references, section links, and a text alternative. Shows the current simulated
  tools and in-memory stores accurately.
- Added a real Execution monitor for six agent stages. Running stages animate;
  blocked, skipped, completed, and failure states have text. Mobile gets a
  collapsible monitor above chat. Reduced-motion preferences disable animation.
- Example requests now populate a draft rather than executing immediately.
- Added conversation history, reload/recovery controls, and JSON conversation exports.
  Disabled agent switching and new-chat controls during active work and preserved
  drafts on failure. Original per-turn trace and tool/source evidence remain available.
- Added filtered JSON event exports, including filter metadata and explicit 200-event
  view limit. Exports include original evidence and are not sanitized audit archives.
- Improved global keyboard focus, skip navigation, mobile menu focus containment,
  Escape dismissal, and focus return. Page changes reset scrolling and update titles.
- Standardized cards and allowed metric labels/notes to wrap on small screens.
  Added accessible firewall input/channel labels and disabled competing preset scans.
- Saved desktop overview/architecture and mobile overview review screenshots under
  `docs/screenshots/`.

### Backend reliability and security

- Wrapped existing graph nodes with an optional status callback that reports real
  start/completion boundaries without changing the graph's security logic.
- Added authenticated `GET /api/sessions/{id}/progress`, with owner/staff checks and
  request UUID, lifecycle state, current stage, stage statuses, and timestamps.
  Progress never publishes unfinished model output, tool arguments, or provider errors.
- Added atomic per-session execution reservation. Overlapping sends and closes now
  return 409. Completion/failure releases the reservation in a finally block.
- Added optional UUID request identifiers; any repeated ID in the same session is
  rejected for the process lifetime, including after failed attempts. Existing
  callers may omit the field. This is replay rejection, not cached-response replay.
- Rejected whitespace-only messages. Recorded planning decisions even when no tool
  is needed or the configured tool-step limit has been reached.
- Added a thread-safe login limiter: ten attempts per ASGI client address per rolling
  minute, at most 4,096 peer buckets, expiry, and 429/Retry-After responses. It never
  directly trusts arbitrary forwarding headers. Full capacity rejects new peers.
- Moved password verification off the async event loop and performed a dummy hash
  check for unknown accounts to reduce username timing differences.
- Added API `Cache-Control: no-store`, plus nosniff, anti-framing, and no-referrer
  response headers.

### Client reliability and performance

- Made API errors more useful, including network failures and validation messages.
  A stale unauthorized response cannot clear a newer authentication token.
- Only persist a login token after profile loading succeeds; clean up failed logins.
- API polling uses cancellation, 15-second read timeouts, non-overlapping requests,
  hidden-tab pause, and stale-result guards. Writes are never automatically retried.
- Lazy-loaded routes and added loading/error boundaries. Main JS entry decreased
  from approximately 726 KB to 236 KB minified in local builds; charts load separately.
  This measures the entry bundle, not a reduction of the entire application's code.
- Added configurable `AEGIS_API_TARGET` for local API proxying, retaining port 8000
  as the default. No runtime dependencies were added.

### Documentation

Updated root README, frontend README, environment example, and architecture notes.
Added `docs/operator-guide.md` with a practical finance-assistant review flow,
recovery behavior, permissions, access considerations, and prioritized future work.

### Validation

- Backend: **144 tests passed**, including the existing red-team security gate.
- Added eight regression tests covering actual in-flight progress, ownership,
  terminal blocking, concurrency/close conflicts, failure cleanup, UUID replay,
  blank input, throttling/expiry/capacity, and defensive headers (some cases share tests).
- Ruff: passed for `app`, `tests`, and `evaluation`.
- Frontend: TypeScript check and Vite production build passed.
- Browser: verified administrator sign-in, guided navigation, normal grounded answer,
  blocked injection and its trace, architecture node selection, restricted-role
  navigation, and 390-pixel mobile containment. Desktop review used a 1440-pixel
  viewport. No document-level horizontal overflow in checked mobile views.
- Browser download confirmation was not completed: the browser automation's download
  wait timed out. JSON export code compiled, but successful disk download is not
  included in the verified claims above.
- One existing Starlette/AnyIO deprecation warning remains in the test environment.

### Remaining limits / deployment notes

This is a stronger pilot/evaluation workspace, not a completed production platform.
Use one API worker: execution locks, progress, login budgets, request IDs, sessions,
trust, and events are process-local. Sessions/history still need retention limits.
The RAG index has its existing local persistence; operational PostgreSQL persistence
is still future work. Production needs shared throttling and locking, trusted proxy
configuration, durable audit retention, organization identity and tenant isolation,
and reviewed integrations for real tools. The firewall remains signature-based.
Fast agent runs may finish between progress polls; no fake timing is introduced.

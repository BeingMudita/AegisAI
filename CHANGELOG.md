# Changelog

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

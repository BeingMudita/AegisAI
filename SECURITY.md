# Security policy

AegisAI is a security layer, so we treat flaws in it seriously, including bypasses
that only work against its own controls.

## Reporting a vulnerability

Please **do not open a public issue** for a vulnerability. Report it privately
through GitHub's
[private vulnerability reporting](https://github.com/BeingMudita/AegisAI/security/advisories/new)
for this repository.

Include:

- the affected component (firewall, gateway, approvals, RAG, auth, dashboard…) and
  commit or version;
- steps to reproduce, ideally an input that can be added to `attack-scenarios/`;
- the impact you observed: what the attacker could make an agent *do* or *read*.

We aim to acknowledge reports within 3 working days and to agree on a fix and
disclosure date with you. Reporters are credited in the changelog unless they
prefer otherwise.

## What counts as a vulnerability

In scope, with examples:

| Area | Examples |
|---|---|
| Gateway bypass | A tool runs without passing every checkpoint; a disabled tool runs; an argument reaches a domain outside the allow-list |
| Approval bypass | A `requires_approval` tool executes without an admin decision, executes twice, or survives a failed re-check |
| Isolation | Red-team runs or another user's session affect live trust, events or data |
| Data leakage | Secrets or PII marked sensitive reach an answer, an export or a log they should not |
| Auth and roles | Privilege escalation between agent, analyst and admin; session or token misuse |
| Audit integrity | Erasing or forging security events in PostgreSQL mode |

**Not a vulnerability on its own:** a prompt injection that the firewall scores
as ALLOW but that the gateway still contains. Paraphrased attacks are a documented
limitation of signature detection (see the [threat model](docs/threat-model.md#8-residual-risks)).
Please still send them as new benchmark cases; they make the evaluation more honest.
They become vulnerabilities when they lead to an action or disclosure that a
guarantee in the threat model says cannot happen.

## Supported versions

Only the latest commit on `main` receives fixes. AegisAI is pre-1.0.

## Deployment hardening checklist

Before exposing AegisAI to real users:

- [ ] `ENVIRONMENT=production`. The API refuses to start while `JWT_SECRET` or any
      `SEED_*_PASSWORD` is still a development default.
- [ ] `STORAGE_BACKEND=postgres` with migrations applied
      (`python -m app.database.migrate --seed`). Memory mode is single-worker and
      loses state on restart.
- [ ] TLS terminated at the edge, `CORS_ORIGINS` set to the dashboard origin only,
      and `FORWARDED_ALLOW_IPS` set to your proxy's address (the login throttle uses
      the client address uvicorn derives; the image trusts private networks by
      default, which is wrong if clients themselves are on a private network).
- [ ] An edge rate limiter in front of the API. Built-in limits are per tool, per
      login address and per account, not per user overall.
- [ ] Install from `backend/requirements.lock` (hash-pinned) and keep CI's
      `pip-audit` / `npm audit` steps green.
- [ ] Review `backend/app/policies/default_policies.yaml`: kill switches for tools you
      don't need, `min_trust` per tool, and `requires_approval` for anything with
      external effect.
- [ ] Review agent policies (`app/policies/examples/*.json` or the `policies` table):
      allowed tools, domain allow-lists and sensitive-data categories.
- [ ] Run the Red-team lab (or `evaluation/run_eval.py`) after every change to rules,
      policies or thresholds, and check the Threat coverage page.
- [ ] Treat JSON exports as sensitive. Conversation exports contain original
      messages and retrieved context.
- [ ] Replace the sandboxed tools only with adapters that use scoped credentials,
      timeouts and output validation, and keep the gateway as their only path.

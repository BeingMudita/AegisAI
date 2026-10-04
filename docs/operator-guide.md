# AegisAI operator guide

## A practical use case: reviewing a finance assistant

AegisAI is a useful sandbox for evaluating a retrieval assistant before connecting
it to real systems. The supplied finance corpus and simulated tools let operators
test document poisoning, domain restrictions, and sensitive-data handling without
sending actual email or querying production records.

1. **Prepare knowledge.** Sign in as an administrator, open Knowledge base, and
   upload a policy document with a meaningful source name and appropriate trust.
   Watch the existing ingestion queue progress through parsing, screening,
   embedding, and indexing. Review quarantined chunks and test retrieval.
2. **Review capabilities.** Open Policies & tools and inspect the chosen agent's
   allowed tools, approved domains, and sensitive-data categories. Use Architecture
   to understand where each control runs; selecting a node reveals details and a
   link to the relevant workspace section.
3. **Run a normal request.** Open Agent workspace and select “Approval thresholds.”
   Review the draft, then send. Check the answer's source evidence and security
   trace. The execution monitor displays actual node states, including repeated
   planning/tool checks. Quick requests can finish between 400 ms polls.
4. **Exercise a boundary.** Send the supplied off-domain email example. Inspect
   the denied tool's checkpoint evidence. Attacks alter the shared agent's trust;
   use an isolated deployment for evaluation.
5. **Investigate.** Staff can filter Security events and inspect details. Export
   the filtered view (up to 200 events) or a complete conversation as JSON.
   Conversation exports include original messages and retrieved context, so they
   are evidence files rather than universally sanitized reports.
6. **Recover after an interruption.** Choose the conversation from history and
   reload it before repeating an uncertain request. Leaving the page does not
   cancel a server-side turn. An overlapping send or close returns 409. Reusing
   a request UUID also returns 409, including after a failed attempt.

## Access and accessibility

All authenticated users have the guided overview, agent workspace, architecture,
knowledge search, firewall lab, and their allowed policy views. Staff additionally
have event/trust visibility. Existing backend ownership and role checks remain
authoritative; hiding a navigation item is not an access control.

The mobile menu traps keyboard focus, closes with Escape, and returns focus to its
opener. All architecture nodes work with Tab and Enter; the connection list is a
text alternative. A skip link, chart table views, status text, and reduced-motion
support complement the visual presentation. On narrow screens the diagram scrolls
inside its own region and the execution monitor is a disclosure above the chat.

## Deployment boundaries

- **Storage.** With `STORAGE_BACKEND=memory` (the default) use one API worker:
  sessions, request IDs, progress, users, policies, trust, gateway state and events
  are process-local and lost on restart. With `STORAGE_BACKEND=postgres` all of them
  are durable and shared, so several workers or replicas can run behind a load
  balancer: session locks, replay rejection, rate limits and the login throttle
  hold across workers. Session histories and the audit log are not yet pruned
  (retention arrives in Phase 10).
- The login limiter permits 10 attempts per client address per rolling minute,
  including successful attempts. In memory mode it retains at most 4,096 active
  peer buckets and fails closed for new peers when full; in Postgres mode the
  budget is shared by every worker. It uses the ASGI client address, not raw
  forwarded headers. Configure proxy trust in the ASGI server and deploy a shared
  edge limiter before scaling; users behind one NAT may share a budget.
- Progress returns only stage/status metadata, not unfinished model text, prompts,
  tool arguments, or provider errors. Final traces retain the existing evidence.
- Evidence exports are snapshots, not signed or tamper-evident audit archives.
- Tools remain simulations. Production integrations need scoped credentials,
  transport controls, timeouts, and review of consequential actions.
- The firewall remains signature-based. Do not treat a passed scan as proof that
  content is harmless. Its defense is combined with deny-by-default tool controls.

## Next engineering priorities

1. ~~Migrate operational stores to PostgreSQL; use transactions, shared request IDs,
   and distributed execution locks before adding workers or replicas.~~ Done (Phase 9).
2. Add durable, access-controlled audit retention, session expiry, quotas, and
   pagination for large deployments.
3. Integrate organization identity (SSO/OIDC), tenant isolation, and per-principal
   abuse controls; evaluate the effect of untrusted callers on shared agent trust.
4. Add carefully scoped real tool adapters and an explicit approval workflow for
   high-impact actions. Keep the gateway as their only execution path.
5. Extend the existing red-team evaluation with paraphrased attacks before adding
   a model-based classifier or making stronger detection claims.

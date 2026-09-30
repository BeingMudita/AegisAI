# AegisAI Architecture

> Living document — expanded as phases are implemented.

## Overview

AegisAI is a zero-trust security layer positioned between untrusted input and
an autonomous agent's ability to act. Every inbound message, retrieved
document, and requested tool call passes through defensive checkpoints.

## Request lifecycle

```
Input ─▶ Firewall ─▶ Trust Engine ─▶ Policy Engine ─▶ Agent (LangGraph)
                                                          │
                                          RAG ◀───────────┤
                                          Tools ◀─────────┘
                                                          │
                                                    Telemetry (audit log)
```

1. **Firewall** — scans input for prompt-injection / jailbreak signatures.
2. **Trust Engine** — assigns/updates trust scores for the actor, source, and tool.
3. **Policy Engine** — evaluates declarative rules (`policies/`) against the action.
4. **Agent** — LangGraph orchestrates the reasoning loop, calling RAG and Tools.
5. **Telemetry** — every decision is logged for audit and evaluation.

## Component map

| Package | Role |
|---------|------|
| `app/api` | FastAPI routes / schemas |
| `app/firewall` | Injection detection |
| `app/trust` | Trust scoring |
| `app/policies` | Rule definitions + enforcement |
| `app/agents` | LangGraph workflows |
| `app/rag` | Retrieval over pgvector |
| `app/tools` | Permissioned tool integrations |
| `app/telemetry` | Audit logging |
| `app/database` | Models, sessions, migrations |

## Data stores

- **PostgreSQL + pgvector** — relational data and vector embeddings.

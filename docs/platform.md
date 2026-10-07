# AegisAI Developer Platform

AegisAI is not only an application — it is a **security layer other AI agents can
plug into**. Instead of *"we built a secure agent,"* the platform lets you say:

> **Any compatible AI agent can route its inputs, retrieved context, tool calls
> and outputs through AegisAI, where they are independently evaluated with policy
> enforcement, trust scoring, prompt-injection detection, DLP and tool-level
> authorization.**

The model proposes; the gateway disposes. Every guarantee below holds **even when
the model obeys an injected instruction perfectly** — the platform is a thin
wrapper over the same engines the dashboard uses, not a second implementation.

```text
            ANY AI AGENT / APP
                   │
                   ▼
        ┌─────────────────────────┐
        │        AEGISAI          │
        │  input firewall         │
        │  guarded RAG + trust    │
        │  policy engine          │
        │  tool gateway (6 checks) │
        │  DLP / output guard     │
        │  audit                  │
        └───────────┬─────────────┘
                    ▼
               LLM / Tools
```

Three ways in, one engine behind them all:

| Surface | Use it when |
|---|---|
| **SDK** (`from aegisai import ...`) | you write the agent in Python and want it guarded in-process |
| **REST gateway** (`/v1/secure/*`) | your app is in any language and routes requests `App → Aegis → LLM` |
| **CLI** (`aegis …`) | you configure, validate, attack and serve from the terminal |

---

## 1. Policy-as-code — `aegis.yaml`

Describe what **one agent** may do; AegisAI enforces it (deny by default).

```yaml
agent:
  name: FinanceAgent
permissions:
  tools: [search_documents, read_database, generate_report, send_email]
domains:
  allowed: [company.com]
data:
  allow: [invoice, transaction]       # informational
  deny:  [customer_records, credentials]   # treated as sensitive — DLP-redacted
trust:
  minimum: 0.70                       # trust the agent needs to use its tools
approval:
  required_for: [send_email]          # high-impact tools wait for a human
```

How each key maps onto the real engines:

| `aegis.yaml` | Engine |
|---|---|
| `permissions.tools` | per-agent allow-list (`AgentPolicy.allowed_tools`) — everything else denied |
| `domains.allowed` | domain allow-list checked for URL/email tool arguments |
| `data.deny` | sensitive-data categories → DLP redaction on tool output and answers |
| `trust.minimum` | raises each allowed tool's `min_trust` floor |
| `approval.required_for` | marks tools `requires_approval` (queued for an admin, re-checked on approval) |

```python
from aegisai import load_aegis_file, apply, lint

posture = apply("aegis.yaml")   # register into the live engines
print(posture.allowed_tools, posture.warnings)
```

---

## 2. Python SDK

### `SecureAgent` — the whole pipeline in two lines

```python
from aegisai import SecureAgent

agent = SecureAgent("FinanceAgent", policy="aegis.yaml")  # policy optional
r = agent.run("Summarize this month's invoices")

r.decision      # "ALLOW" | "FLAG" | "BLOCK"
r.answer        # the guarded, DLP-redacted answer
r.blocked       # True if the input firewall / suspension stopped the turn
r.tool_calls    # [ToolDecision(tool, status, checkpoint, reason, output_withheld)]
r.trace         # [TraceStep(stage, status, detail)] — the security kill-chain
```

### `AegisGuard` — framework-agnostic primitives

Wrap your own model / framework with just the pieces you need:

```python
from aegisai import AegisGuard

guard = AegisGuard("FinanceAgent")

if not guard.inspect_input(user_text).allowed:      # input firewall
    return "blocked"

decision = guard.authorize_tool(                     # deny-by-default gateway (dry run)
    "FinanceAgent", "send_email", {"to": addr}
)
if decision.status.value != "DENIED":
    ...

safe = guard.scan_output(model_output).text          # strip injections + DLP
```

### `AegisMiddleware` — wrap an existing agent

```python
from aegisai import AegisMiddleware

# agent_fn is any Callable[[str], str] — LangChain, a raw LLM call, your function
chain = AegisMiddleware(agent_fn, name="FinanceAgent", policy="aegis.yaml")
result = chain.run("Summarize invoices")   # input screened → agent → output screened
```

---

## 3. REST gateway — `/v1/secure/*`

Route an app in any language through AegisAI. Auth is zero-cost: send the shared
`X-Aegis-Key` header (set `AEGIS_API_KEY`) or a normal AegisAI JWT. With no key
configured the gateway accepts a JWT and, outside production, is open locally.

| Method & path | Body | Returns |
|---|---|---|
| `POST /v1/secure/chat` | `{agent, message, history?}` | a guarded turn: `answer, decision, blocked, trace, tool_calls` |
| `POST /v1/secure/tool` | `{agent, tool, arguments}` | pre-flight authorization: `status, decision, checks` (does **not** execute) |
| `POST /v1/secure/scan` | `{text, channel?}` | firewall verdict: `action, score, categories, reason` |
| `GET  /v1/secure/agents` | — | configured agents and what each may do |

```bash
# Chat
curl -s localhost:8000/v1/secure/chat -H 'content-type: application/json' \
  -H 'X-Aegis-Key: <key>' \
  -d '{"agent":"FinanceAgent","message":"What are the invoice approval thresholds?"}'

# Tool pre-flight — a gmail recipient is refused at the domain check
curl -s localhost:8000/v1/secure/tool -H 'content-type: application/json' \
  -d '{"agent":"FinanceAgent","tool":"send_email","arguments":{"to":"x@gmail.com"}}'
# → {"decision":"BLOCK","status":"DENIED","checks":[... {"checkpoint":"domain","passed":false} ]}
```

---

## 4. CLI — `aegis`

Available as `aegis <cmd>` after `pip install -e backend`, or always as
`python -m app.platform.cli <cmd>` from `backend/`.

| Command | What it does |
|---|---|
| `aegis init` | write a starter `aegis.yaml` |
| `aegis scan [path] [--prompt TEXT]` | validate a policy file and print the resolved posture; with `--prompt`, screen text through the firewall (exit 2 on BLOCK) |
| `aegis redteam [--suite firewall,agents]` | run the attack suites against an isolated sandbox and print recall / precision / scenarios |
| `aegis serve [--host --port --reload]` | start the gateway (the FastAPI app) |
| `aegis inspect [--url]` | open the operator dashboard |

```bash
aegis init && aegis scan aegis.yaml --prompt "ignore all previous instructions"
aegis redteam
aegis serve --reload
```

---

## Notes & limitations

- **Storage.** The SDK/`apply()` path registers policies in a runtime override map
  that `get_policy` consults first, so an `aegis.yaml` is visible everywhere in the
  process immediately. In `postgres` (multi-worker) mode this override is per-process;
  persisting developer policies to the database is a later step.
- **No new controls.** Everything here calls the existing firewall, trust engine,
  policy engine, tool gateway, DLP and agent runtime. See
  [architecture](architecture.md) and the [threat model](threat-model.md).

# AegisAI Universal Runtime Integration Layer

The scanner, SDK, REST gateway and policy-as-code all assume you can *reach* the agent's
code. The integration layer removes that assumption: it takes an **existing agent**, does
**not** rewrite its security logic, and routes its AI/tool interactions through AegisAI.

```
OpenAI ─────┐
LangGraph ──┤
MCP ────────┼──▶  Aegis Event Protocol  ──▶  Security Engine  ──▶  ALLOW / APPROVAL / BLOCK
Node agent ─┤
Custom ─────┘
```

Everything below reuses the real firewall, trust engine, tool gateway and DLP — there is no
second copy of any security control.

---

## 1. The Aegis Security Event Protocol

A framework-neutral contract (`app/platform/protocol/`). Every integration is translated into
one of five events *before* it reaches the engine, so the core never learns what framework an
agent uses.

| Event           | Payload            | Screened by                       |
| --------------- | ------------------ | --------------------------------- |
| `INPUT`         | user text          | input firewall                    |
| `RETRIEVAL`     | documents / chunks | firewall (quarantines injections) |
| `TOOL_PROPOSAL` | tool + arguments   | deny-by-default tool gateway      |
| `TOOL_RESULT`   | tool output        | firewall + DLP                    |
| `OUTPUT`        | assistant text     | firewall + DLP                    |

A `TOOL_PROPOSAL` in:

```json
{ "event_type": "TOOL_PROPOSAL", "agent": "finance-agent",
  "tool": { "name": "send_email", "arguments": { "to": "attacker@gmail.com" } } }
```

An `AegisDecision` out:

```json
{ "decision": "BLOCK", "reason_code": "untrusted_external_destination",
  "checks": { "registry": "PASS", "policy": "PASS", "domain": "FAIL" } }
```

```python
from app.platform.protocol import AegisEvent, get_security_engine

decision = get_security_engine().evaluate(
    AegisEvent.tool_proposal("finance-agent", "send_email", {"to": "attacker@gmail.com"})
)
print(decision.decision, decision.reason_code)   # Decision.BLOCK untrusted_external_destination
```

---

## 2. The proxy

`app/platform/proxy/` exposes the engine over HTTP. It is mounted in the main app and can also
run standalone (`aegis proxy`).

| Endpoint                  | Purpose                                                  |
| ------------------------- | -------------------------------------------------------- |
| `POST /v1/chat/completions` | Drop-in **OpenAI-compatible** endpoint, guarded end to end |
| `POST /v1/proxy/tool`     | Authorize one tool call (dry run) — the enforcement point |
| `POST /v1/proxy/output`   | Screen outbound text (strip injections, redact PII)      |
| `POST /v1/proxy/chat`     | A full guarded turn (input → upstream → output)          |
| `POST /v1/proxy/mcp`      | Screen an MCP `tools/call` before it reaches its server  |

The **upstream** is where screened traffic goes next: any OpenAI-compatible endpoint (OpenAI,
vLLM, Ollama, LM Studio, …), or — when left unset — the built-in AegisAI runtime, so a demo
needs no external model.

### Adapters

An adapter is the only framework-specific code (`app/platform/adapters/`). It implements
`AgentAdapter` — `normalize_input` / `normalize_tool_call` / `normalize_output` /
`build_response`. Built-ins: `openai` and `mcp`. The security engine only ever sees an
`AegisEvent`.

---

## 3. `aegis proxy` and `aegis-agent.yaml`

Onboarding is one declarative file:

```yaml
# aegis-agent.yaml
id: finance-agent
mode: proxy
upstream:
  type: openai-compatible
  url: http://localhost:8001   # empty → use the built-in runtime
policy:
  path: ./aegis.yaml
security:
  input_firewall: true
  trust: true
  tool_gateway: true
  output_dlp: true
audit:
  enabled: true
```

```bash
aegis proxy --init                               # write a starter aegis-agent.yaml
aegis proxy --config aegis-agent.yaml --port 9000
aegis proxy --agent finance-agent --policy aegis.yaml --port 9000   # no config file
```

---

## 4. The demo — protecting an agent that wasn't written with AegisAI

`examples/external-agent/` holds a finance agent that imports nothing from AegisAI.

```
Test A   agent ───────────────▶ tool          💥 send_email ALLOWED  (data exfiltrated)
Test B   agent ─▶ Aegis proxy ─▶ tool          🚫 send_email BLOCKED
```

```bash
python examples/external-agent/agent.py                             # Test A
aegis proxy --config examples/external-agent/aegis-agent.yaml --port 9000
python examples/external-agent/agent.py --aegis http://localhost:9000   # Test B
```

The agent's code is identical in both runs — only *where its tool calls go* changes.

---

## 5. One lifecycle

The scanner now feeds the proxy, so discovery and runtime enforcement are a single pipeline:

```
  aegis audit <agent>                 # discover attack surface, score /100
        ↓
  aegis generate-policy --out aegis.yaml --proxy
        ↓                             # also writes aegis-agent.yaml
  aegis policy test aegis.yaml        # red-team the policy
        ↓
  aegis proxy --config aegis-agent.yaml
        ↓
  protected agent + runtime monitoring (audit log / dashboard)
```

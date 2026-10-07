# AegisAI AI-DevSecOps Platform

AegisAI now covers an agent's whole life — **before, during and after** deployment,
and **during development** — with one security core behind all of it.

```
                    DEVELOPER
                        │
                        ▼
                ┌───────────────┐
                │   REGISTRY    │  connect → scan → protect
                └───────┬───────┘
                        ▼
                 Policy + Red-Team
                        ▼
                 GitHub Security Gate ── FAIL ─▶ block the PR
                        │ PASS
                        ▼
                   AEGIS PROXY
                        ▼
                     AI Agent
                        ▼
              Runtime Adaptive Security
             (trust · DLP · tool gateway)
                        ▼
                Autopilot recommendations
```

| Stage | Feature | Entry points |
| --- | --- | --- |
| Onboard | **Agent Registry** | `POST /api/registry/agents` → `/scan` → `/protect` |
| Develop | **Security Gate** + **GitHub Action** | `aegis gate`, `.github/actions/aegis-security` |
| Runtime | **Adaptive Security** | the proxy + `GET /api/adaptive/agents/{id}` |
| Improve | **Autopilot** | `GET/POST /api/autopilot/agents/{id}/…` |

---

## 1. Agent Registry — connect → scan → protect

A developer declares an agent; AegisAI runs the whole front half of the lifecycle
and hands back a deployment config. No need to know `aegis.yaml`, adapters or the
proxy up front.

```bash
# Register
curl -XPOST /api/registry/agents -d '{
  "id": "finance-agent", "framework": "openai-compatible",
  "tools": ["read_database", "send_email"], "data": ["customer_records"]
}'

# Scan (DISCOVER → AUDIT → GENERATE POLICY → RED-TEAM → CONFIGURE)
curl -XPOST /api/registry/agents/finance-agent/scan

# Protect → deployment configuration (aegis.yaml + aegis-agent.yaml + run command)
curl -XPOST /api/registry/agents/finance-agent/protect
```

Pure orchestration over the scanner, the gate and the proxy config — see
[`app/platform/registry.py`](../backend/app/platform/registry.py).

---

## 2. Runtime Adaptive Security

The static pipeline is `Agent → Aegis → Decision`. Adaptive security adds the loop:

```
Agent → Aegis → Decision → observe behaviour → update risk → adapt enforcement
```

Each tool call is observed. Behaviour that deviates from the agent's baseline — a
tool it has never used, a sensitive read followed by an external send, a burst of
calls — costs trust. As trust falls, the agent changes **posture**, and the proxy
enforces each posture more strictly:

```
 NORMAL ──▶ SUSPICIOUS ──▶ RESTRICTED ──▶ QUARANTINED
  trust      0.40–0.60      0.20–0.40       < 0.20
  ≥ 0.60     approve        block           block
             risky tools    risky tools     everything
```

A worked example — a FinanceAgent that starts exfiltrating:

```
query_invoice ×N        trust 0.91   NORMAL       ✅ allowed
query_customer_database trust 0.72   SUSPICIOUS   ⏸ risky tools need approval
export customers.csv    trust 0.41   RESTRICTED   🚫 risky tools blocked
send_email → gmail.com  trust 0.18   QUARANTINED  🚫 everything blocked
```

The trust number still lives in the trust engine (so the dashboard, audit log and
tool gateway all agree); the monitor only observes, penalises and overlays
posture. An administrator lifts a quarantine with `POST /api/adaptive/agents/{id}/reset`.
See [`app/platform/adaptive.py`](../backend/app/platform/adaptive.py).

---

## 3. Aegis Autopilot — policy improvement, human-approved

Autopilot watches what an agent actually does at runtime and proposes tightening
changes. It **never** edits a production policy silently — each proposal is a
recommendation a human can **Simulate**, **Apply** or ignore.

```
⚠️ POLICY RECOMMENDATION

Observed:  send_email called with off-list destination (gmail.com)
Risk:      HIGH
Suggested: restrict send_email → company.com

[ Apply ]  [ Reject ]  [ Simulate ]
```

```bash
GET  /api/autopilot/agents/{id}/recommendations     # analyse behaviour
POST /api/autopilot/agents/{id}/simulate            # score before/after a change
POST /api/autopilot/agents/{id}/apply               # apply it (admin only)
```

Recommendations are derived from the tool-gateway request log and the adaptive
monitor's observed calls: wildcard domain allow-lists, off-list destinations,
granted-but-unused tools, and high-impact tools running without approval. See
[`app/platform/autopilot.py`](../backend/app/platform/autopilot.py).

---

## 4. Continuous Red Teaming — the security gate

`aegis policy test` answers *"attack it now."* The gate answers *"may this change
ship?"* — it bundles the scanner's score, its high-severity findings and a live
red-team run into one verdict against a threshold.

```bash
aegis gate FinanceAgent --threshold 90
```

```
AEGIS SECURITY GATE
    --------------------------------------------
    Agent            FinanceAgent
    Security score   91/100 (A)   threshold 90
    Prompt Injection         3/3 ✓
    Data Exfiltration        5/5 ✓
    Tool Abuse               1/1 ✓
    --------------------------------------------
    ✓ security_score: Score 91/100 (grade A); threshold 90.
    ✓ no_high_findings: No HIGH-severity findings.
    ✓ red_team: 17/17 agent scenarios defended.

    ✓ Deployment permitted
```

Exit code `0` on PASS, `2` on FAIL — ready for CI. Also `--json` and `--markdown`,
and `POST /api/gate`. See [`app/platform/gate.py`](../backend/app/platform/gate.py).

---

## 5. GitHub Action — DevSecOps for agentic AI

The gate as a pull-request check. If someone weakens `aegis.yaml` — say
`send_email` gets `allowed_domains: ["*"]` — the gate catches it and blocks the PR.

```yaml
# .github/workflows/aegis-security.yml
name: AegisAI Security
on: [pull_request]
permissions:
  contents: read
  pull-requests: write
jobs:
  security-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/aegis-security
        with:
          target: FinanceAgent
          threshold: "90"
          redteam: "true"
```

The action installs AegisAI, runs `aegis gate`, writes the report to the job
summary, posts it as a PR comment, and fails the job (blocking the deploy) when
the gate fails. See [`.github/actions/aegis-security/`](../.github/actions/aegis-security/).

```
🛡️ AegisAI Security Report

Security Score: 91/100  ·  Threshold: 90
✓ security_score   ✓ no_high_findings   ✓ red_team (17/17)

Status: ✅ PASS
```

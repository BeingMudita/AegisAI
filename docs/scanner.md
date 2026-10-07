# AegisAI Agent Security Scanner

The scanner adds the front half of the security lifecycle on top of the platform:

```
SCAN (audit) → GENERATE (policy) → TEST (red-team) → FIX → PROTECT (serve/gateway) → MONITOR
```

Point AegisAI at an agent and it builds a **security profile** (tools, data sources, external
destinations, permissions, trust requirements, data flows), scores it **out of 100** against seven
risk categories, generates a **least-privilege `aegis.yaml`**, and lets you **red-team** it — all
reusing the real tool registry, policy engine, firewall, trust engine and red-team sandbox.

---

## 1. Scan — `aegis audit <target>`

`<target>` can be a known agent, an `aegis.yaml`, or an agent **source directory** (best-effort
static discovery of tools, LLM provider, data sources and external hosts).

```bash
aegis audit FinanceAgent              # a known, AegisAI-protected agent
aegis scan-agent ./my-langchain-app   # heuristic scan of any agent repo
aegis audit FinanceAgent --html report.html   # also write a shareable HTML report
aegis audit FinanceAgent --json       # machine-readable
```

```
AegisAI Security Report — FinanceAgent
    AGENT SECURITY SCORE   91 / 100   (A)
    --------------------------------------------
    Prompt Injection               ✓ LOW
    Indirect Injection             ✓ LOW
    Excessive Tool Permission      ⚠ MEDIUM
    Sensitive Data Exposure        ✓ LOW
    Unsafe External Destinations   ✓ LOW
    Missing Human Approval         ✓ LOW
    Output Leakage                 ✓ LOW
```

### The scoring model

Seven categories, each with a fixed weight (summing to 100). A category's penalty is its weight ×
severity multiplier (**HIGH** 1.0 · **MEDIUM** 0.5 · **LOW** 0.0); `score = 100 − Σ penalties`.

| Category | Weight | OWASP | HIGH when |
|---|--:|---|---|
| Excessive Tool Permission | 18 | LLM06 | a CRITICAL tool is allowed, or ≥2 HIGH tools |
| Missing Human Approval | 18 | LLM06 | a HIGH/CRITICAL or send-capable tool runs without approval |
| Sensitive Data Exposure | 16 | LLM02 | a tool touches sensitive data but no DLP categories are declared |
| Unsafe External Destinations | 14 | LLM02 | an external-capable tool has no domain allow-list |
| Indirect Injection | 12 | LLM01 | untrusted data sources and the agent isn't behind AegisAI |
| Prompt Injection | 12 | LLM01 | no input firewall in front of the model |
| Output Leakage | 10 | LLM05 | sensitive data can leave with no output DLP |

A locked-down AegisAI agent scores in the 90s; a raw, un-integrated agent with send-capable tools and
no guards scores in the 20s–40s with several HIGH findings and a clear list of fixes.

## 2. Generate — `aegis generate-policy <target>`

Produces a least-privilege `aegis.yaml`: only the discovered tools, external destinations locked to an
internal domain, `approval.required_for` on high-impact tools, `data.deny` from the tools' data
categories, and `trust.minimum: 0.70`.

```bash
aegis generate-policy FinanceAgent --out aegis.yaml
```

## 3. Test — `aegis policy test [path]`

Applies the policy and runs the red-team attack scenarios for that agent against an isolated sandbox
(never touching live state), reporting what was defended.

```bash
aegis policy validate aegis.yaml      # schema + lint
aegis policy test aegis.yaml          # apply + red-team
```

## 4. Protect — `aegis serve`

Deploy the policy behind the gateway (`/v1/secure/*`) or the SDK — see [platform.md](platform.md).

---

## REST

| Method & path | Auth | Returns |
|---|---|---|
| `POST /v1/secure/audit` `{agent}` | API key / JWT | the full `SecurityReport` |
| `POST /v1/secure/generate-policy` `{agent}` | API key / JWT | `{agent, aegis_yaml}` |
| `GET /api/scanner/agents/{agent}/report` | JWT (console) | the `SecurityReport` |
| `GET /api/scanner/agents/{agent}/policy` | JWT | `{agent, aegis_yaml}` |
| `POST /api/scanner/agents/{agent}/test` | JWT | red-team results for the agent |

## Dashboard

The **Security scanner** page (Assure group) renders the whole flow: the score, the seven-category
risk assessment, a permission graph (tools → data sources → external destinations + data flows), the
recommended fixes, the generated `aegis.yaml` (downloadable), and a **Run policy test** button.

## Notes & limits

- **Directory discovery is heuristic** — it reports what it found (and records `notes`); it never
  claims completeness. Auditing a known agent or an `aegis.yaml` is exact.
- The scoring model is **deterministic and documented** (the table above), not an opaque metric.
- `policy test` runs in the existing isolated red-team sandbox.
- Live-URL auditing (`audit https://…`) and a forwarding `aegis proxy` are planned follow-ups.

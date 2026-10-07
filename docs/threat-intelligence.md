# Threat Intelligence & Attack-Surface Analysis

Two composition-level capabilities that make AegisAI *collectively* and
*structurally* defensive, rather than only reacting to each event in isolation.

---

## 1. Aegis Threat Intelligence Engine

An agent learns from its own behaviour through the trust engine. Threat
intelligence lets every agent learn from the security events of the **whole
platform**: when one agent is attacked, AegisAI distils a normalized **threat
signature** and shares it, so another agent is warned about a similar attack
*before it experiences it*.

```
Agent A ─▶ attack detected ─▶ threat signature ─┬─▶ Agent B  preemptive detection
                                                 └─▶ Agent C  preemptive detection
```

A signature is a fingerprint of the malicious content (word-shingles of its
normalized text) plus metadata:

```json
{
  "type": "DATA_EXFILTRATION",
  "severity": "HIGH",
  "categories": ["DATA_EXFILTRATION", "INSTRUCTION_OVERRIDE"],
  "tool": "send_email",
  "destination": "external",
  "hits": 3,
  "agents": ["finance-agent", "research-agent"]
}
```

**How it is wired in.** The security engine ([`engine.py`](../backend/app/platform/protocol/engine.py))
does two things on every `INPUT`, `RETRIEVAL`, `TOOL_RESULT` and `OUTPUT`:

1. **Learn** — a firewall FLAG/BLOCK, or a sensitive external send refused at the
   `domain` checkpoint, is recorded as a signature.
2. **Match** — the content is compared to known signatures by token overlap
   (Jaccard ≥ 0.6). A match to a known **HIGH** signature *escalates* an otherwise
   clean verdict (`ALLOW → FLAG`, a retrieved doc is quarantined) with reason code
   `known_attack_pattern`.

The payoff: a *variant* of a known attack is caught even when it falls below a
single agent's firewall threshold.

```bash
aegis threats                      # the shared feed
GET  /api/threat-intel/signatures  # feed as JSON
POST /api/threat-intel/match       # test content against known signatures
```

No new detector — it reuses what the firewall already found, across agents.

---

## 2. Attack-Surface Analysis — paths, blast radius, risk-guided red teaming

Individual checks ask *"is this one tool / domain / data category allowed?"*
Attack-surface analysis asks the harder question: *"what do the permissions allow
when you **compose** them?"* See [`attackgraph.py`](../backend/app/platform/attackgraph.py).

### Attack-surface graph & paths

From the scanner's profile it builds a graph (agent · tools · data · destinations ·
sources) and enumerates dangerous **paths** through it:

```
external web pages → agent → read_database → send_email → ANY external host
                                                              🔴 data-exfiltration path
```

### Blast radius

If the agent were compromised, how much damage could it do? A deterministic
0–100 score over tool risk, external exposure, sensitive reach, missing approvals
and dangerous paths — giving the policy generator a measurable objective.

```
aegis blast weak-agent
```

```
ATTACK SURFACE — weak-agent
    Blast radius     🔴 71/100
    Accessible data  customer_records, database, web
    Destinations     ANY external host
    Dangerous acts   send_email, web_fetch

    Attack paths
      🔴 [HIGH] weak-agent → read_database → send_email → ANY external host
      🔴 [HIGH] external web pages → weak-agent → read_database → send_email → ANY external host

    Hardening (least privilege)
      Before 71  →  After 50   (−21)
```

```bash
GET /api/attack-surface/agents/{id}            # graph + paths + blast + risk focus
GET /api/attack-surface/agents/{id}/blast      # blast radius only
GET /api/attack-surface/agents/{id}/hardening  # before/after least-privilege tightening
```

### Risk-guided red teaming

Rather than "run 50 attacks," the dangerous paths tell the red team **where** to
attack. The gate and `aegis blast` surface a prioritized focus (most dangerous
path first):

```
Risk focus   Indirect Injection → Data Exfiltration → Prompt Injection
```

so red-team effort is spent on the compositions that actually matter for this
agent.

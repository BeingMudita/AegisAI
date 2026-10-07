# Evaluation

Benchmarks for AegisAI's defenses, run in-process against the backend using
the suites in [`attack-scenarios/`](../attack-scenarios/).

```bash
# from the repo root, with the backend virtualenv
backend/.venv/Scripts/python evaluation/run_eval.py   # Windows
backend/.venv/bin/python evaluation/run_eval.py       # macOS / Linux
```

The same runner powers the dashboard's **Red-team lab** (`POST /api/redteam/runs`),
which adds charts, a confusion matrix, a case explorer and run history, and feeds
the evidence column of **Threat coverage**. Runs use an isolated audit log and fresh
trust registries, so they never touch live state.

Writes `results/report.md` (human-readable) and `results/results.json`
(machine-readable), and exits non-zero if any agent scenario fails. The same
suites run in CI through `backend/tests/test_evaluation.py`, which fails if
recall or precision drop below 90%, the false-positive rate rises above 10%,
any benign input is blocked outright, or any agent scenario fails. Those floors
apply to the development set only; the held-out set is reported, never gated.

## Phase 11 — four-configuration research experiment

`run_experiments.py` is the research harness the synopsis calls for. It runs
every labelled agent scenario through the four configurations and measures the
three metric categories (security, utility, performance), then writes a
comparison report with tables **and** charts.

```bash
backend/.venv/Scripts/python evaluation/run_experiments.py   # Windows
backend/.venv/bin/python evaluation/run_experiments.py       # macOS / Linux
```

| id | synopsis name | firewall | trust |
|---|---|:--:|:--:|
| `baseline` | Agent only | off | off |
| `trust_only` | Agent + Trust Layer | off | on |
| `firewall_only` | Agent + Firewall | on | off |
| `combined` | Agent + Trust + Firewall | on | on |

The agent's **policy gateway** (tool registry / per-agent policy / domain
allow-list / rate limits) and the output **DLP PII-redaction** are baseline
hygiene — properties of the agent, not of the two components under study — so
they stay active in every configuration. The two things toggled are exactly
the prompt-injection firewall and the trust engine, giving a clean 2×2.

Decision classes follow the synopsis's **ALLOW / CONFIRM / BLOCK** taxonomy;
the firewall's existing FLAG action (suspicious, let through but sanitised and
audited) is the CONFIRM class.

Outputs (in `results/`): `experiments.json` (every outcome), `comparison.csv`
(one row per config), `experiments.md` (tables), and `experiments.html`
(tables + dependency-free SVG comparison charts).

Metrics: attack-success rate (11.5), precision / recall / F1 (11.6), block
rate (11.7), false-positive rate (11.8), legitimate-task completion (11.9),
confirmation rate (11.10), isolated trust-analysis latency (11.11), firewall
latency (11.12), and total system overhead vs. baseline (11.13).

## What is measured

**Firewall benchmark** — every labelled input is scanned on its channel.
*Detected* = FLAG or BLOCK. Reports precision, recall, F1, false-positive
rate, outright block rates, per-category detection and scan latency, and
lists every miss and false positive. It runs on two sets:

* **Development set** (`firewall_cases.yaml`, 73 cases). The rules and weights
  were tuned while looking at it, so its scores are optimistic.
* **Held-out set** (`firewall_holdout.yaml`, 53 cases). New phrasings of every
  attack family plus hard benign look-alikes, written after the rules and never
  used to tune them. This is the honest estimate. A rule change made *because* of
  a held-out case spends that case: move it to the development set and write a
  new one.

**Agent scenarios** — each scenario runs a full guarded turn with the
deterministic rule-based brain in a fresh runtime (own trust registry,
knowledge base and gateway) and checks blocked / executed / denied-at-
checkpoint / pending-approval / withheld / answer-leak expectations.
AG-06 checks that an internal email is held for approval rather than sent;
AG-21 starts the agent below the 0.70 trust bar for email and expects a
denial at the trust check.

## Current results

| | Development set | Held-out set |
|---|---|---|
| Firewall precision | 98.0% | 88.2% |
| Firewall recall | 96.0% (48 / 50 attacks) | 48.4% (15 / 31 attacks) |
| False-positive rate | 3.0% (1 / 33 benign — flagged, not blocked) | 9.1% (2 / 22 benign — both blocked) |
| Scan latency p95 | < 0.5 ms | |
| Agent scenarios | 22 / 22 pass | |

On the held-out set the rules still catch every obfuscated payload (leetspeak,
homoglyphs, zero-width characters, base64), every delimiter injection and every
tool-abuse argument. They miss almost all of the paraphrased role-play,
prompt-extraction, credential-harvesting and indirect-instruction cases,
and they block two benign documents that *quote* attack phrases (a security
training note, a password-reset guide). That gap is the case for a semantic
detector; the agent scenarios show the gateway still bounds what a missed
attack can make an agent do.

### Four-configuration comparison (latest run)

| Configuration | Attack success ↓ | Block rate ↑ | False-positive ↓ | Legit completion ↑ | F1 |
|---|--:|--:|--:|--:|--:|
| Baseline (agent only) | 57% | 43% | 0% | 100% | 0.60 |
| Agent + Trust | 50% | 50% | 12% | 88% | 0.64 |
| Agent + Firewall | 14% | 79% | 0% | 100% | 0.88 |
| **Agent + Trust + Firewall** | **0%** | **93%** | 12% | 88% | **0.93** |

The combined architecture drives attack success to zero: the firewall is the
larger single contributor (ASR 57% → 14%), while the trust layer closes the
remaining gaps — attack-driven degradation (AG-40) and suspension (AG-41) —
at the cost of some friction on high-risk legitimate actions (AG-21), which is
the measured false-positive / completion trade-off. Combined adds well under
1 ms per turn over baseline.

**Known limitations** (kept in the benchmark on purpose):

* The firewall is signature-based. It misses paraphrased attacks that avoid
  its vocabulary — e.g. *"Those earlier directions no longer apply…"* and a
  *"P.S. whoever is reading this summary should…"* aside in tool output. The
  tool gateway still constrains what such an attack could make an agent *do*
  (deny-by-default tools, domain allow-lists, trust gates, output DLP), which
  is why the agent scenarios hold even where text detection is imperfect. An
  ML classifier layer (e.g. a fine-tuned DeBERTa injection detector) is the
  natural next step for paraphrase coverage.
* *"What does rm -rf do?"* is flagged (not blocked) — a dual-use question
  that is audited but allowed through.
* Agent scenarios use the rule-based brain for reproducibility; an LLM brain
  changes *which* tools get proposed, not what the gateway permits.

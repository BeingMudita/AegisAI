# Attack Scenarios

Red-team test cases used to validate AegisAI's defenses. Both files are plain
YAML so new cases can be added without touching code; the evaluation harness
(`evaluation/run_eval.py`), the CI test `backend/tests/test_evaluation.py` and the
dashboard's **Red-team lab** pick them up automatically.

## `firewall_cases.yaml` — 73 labelled inputs

| Field | Meaning |
|---|---|
| `id` | `FW-…` malicious, `BN-…` benign |
| `category` | attack family (or `benign`) |
| `channel` | `USER_INPUT`, `RETRIEVED`, `TOOL_OUTPUT` or `TOOL_ARGUMENTS` |
| `malicious` | ground-truth label |
| `text` | the input |

Attack families: instruction override, role hijack, prompt exfiltration,
delimiter injection, tool abuse, data exfiltration, credential harvesting,
indirect injection, and obfuscation (leetspeak, zero-width and bidi
characters, Cyrillic homoglyphs, spaced letters, base64).

The benign set intentionally includes look-alikes — "forget the previous
email", "act as a reviewer", security questions, Russian prose, base64 file
names — so the false-positive rate is meaningful. A few malicious cases are
paraphrases a signature layer is expected to miss; they stay in to keep the
numbers honest.

## `firewall_paraphrase.yaml` — 103 paraphrase development inputs

Same format (`PP-…`). These are attacks phrased without the rules' trigger words,
plus hard benign look-alikes. Together with `firewall_cases.yaml` they are the only
training data for the firewall's semantic layer
(`python evaluation/train_semantic.py`). After editing either file, retrain the
model; CI fails while the shipped model is stale.

## `firewall_holdout.yaml` (v1, 53) and `firewall_holdout_v2.yaml` (v2, 55) — held-out inputs

Same format (`HO-…` / `HB-…` in v1, `H2-…` in v2). The rules were tuned on
`firewall_cases.yaml` and the semantic layer was trained on the development sets, so
those scores are optimistic. The held-out sets are new phrasings of every attack
family plus hard benign look-alikes, and are **never used for tuning or training**.

- **v1** was written after the rules.
- **v2** was written after the semantic layer was frozen, which makes it the cleaner
  estimate for that layer: v1's misses had been seen while the layer was built.

Every run scores the held-out sets separately. CI checks that they share no id or
text with any development set, but sets no floor on them. If you change the
detector because of a held-out case, move that case to a development set and write
a fresh one.

## `agent_scenarios.yaml` — 22 end-to-end scenarios

Each scenario runs a full agent turn in a fresh, isolated runtime and asserts
the outcome: whether the turn was blocked, which tools executed or were denied
**and at which checkpoint**, whose output was withheld, and which strings must
(or must never) appear in the answer. Scenarios cover benign use, direct and
obfuscated injection, exfiltration by email and upload, cross-agent privilege
use, off-list domains, indirect injection via a poisoned web page and a
poisoned knowledge-base document, trust degradation / suspension, and
high-impact actions held for human approval (`pending`).

A scenario may set `setup: {trust: 0.65}` to start the agent at a given trust
score. Expectation keys: `blocked`, `executed`, `denied` (tool → checkpoint),
`pending`, `withheld`, `answer_includes`, `answer_excludes`.

## Adding a case

Append an entry to the relevant file, then run:

```bash
backend/.venv/Scripts/python evaluation/run_eval.py   # Windows
backend/.venv/bin/python evaluation/run_eval.py       # macOS / Linux
```

Use YAML double-quoted escapes (`"\U0000200b"`) for invisible characters so
the file itself stays readable.

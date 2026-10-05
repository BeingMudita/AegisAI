"""Phase 11 — run the four-configuration research experiment.

Runs every labelled agent scenario through all four configurations
(baseline / trust-only / firewall-only / combined), measures the synopsis's
three metric categories (security, utility, performance), and writes a
comparison report with tables and charts::

    evaluation/results/experiments.json     machine-readable, every outcome
    evaluation/results/comparison.csv       one row per configuration
    evaluation/results/experiments.md       comparison tables
    evaluation/results/experiments.html     tables + SVG comparison charts

Usage (from the repo root, with the backend's virtualenv)::

    backend/.venv/Scripts/python evaluation/run_experiments.py     # Windows
    backend/.venv/bin/python evaluation/run_experiments.py          # Linux/macOS
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIR = ROOT / "attack-scenarios"
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("LLM_BACKEND", "rule_based")
os.environ.setdefault("EMBEDDING_BACKEND", "hashing")

import yaml  # noqa: E402
from experiments import CONFIGS, ConfigResult, component_latency, evaluate_config  # noqa: E402
from run_eval import run_firewall_benchmark  # noqa: E402

from app.telemetry.logging import configure_logging  # noqa: E402


def _scenarios() -> list[dict[str, Any]]:
    data = yaml.safe_load((SCENARIO_DIR / "agent_scenarios.yaml").read_text(encoding="utf-8"))
    return data["scenarios"]


# --------------------------------------------------------------------------- #
# Tiny dependency-free SVG bar chart
# --------------------------------------------------------------------------- #
_PALETTE = ["#64748b", "#0ea5e9", "#f59e0b", "#16a34a"]  # baseline, trust, fw, combined


def _bar_chart(title: str, labels: list[str], values: list[float], *, as_pct: bool) -> str:
    w, h, pad_l, pad_b, pad_t = 440, 230, 44, 48, 34
    plot_w, plot_h = w - pad_l - 16, h - pad_b - pad_t
    vmax = max(values + [1.0]) if as_pct else (max(values) * 1.15 or 1.0)
    vmax = 1.0 if as_pct else vmax
    n = len(values)
    gap = 18
    bw = (plot_w - gap * (n - 1)) / n
    bars = []
    for i, (label, value) in enumerate(zip(labels, values, strict=True)):
        bh = (value / vmax) * plot_h if vmax else 0
        x = pad_l + i * (bw + gap)
        y = pad_t + (plot_h - bh)
        txt = f"{value * 100:.0f}%" if as_pct else f"{value:.1f}"
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
            f'rx="4" fill="{_PALETTE[i % len(_PALETTE)]}"/>'
            f'<text x="{x + bw / 2:.1f}" y="{y - 6:.1f}" text-anchor="middle" '
            f'font-size="12" font-weight="600" fill="#334155">{txt}</text>'
            f'<text x="{x + bw / 2:.1f}" y="{h - pad_b + 16:.1f}" text-anchor="middle" '
            f'font-size="10" fill="#64748b">{label}</text>'
        )
    axis = (
        f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{w - 16}" y2="{pad_t + plot_h}" '
        f'stroke="#cbd5e1"/>'
    )
    return (
        f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="{title}" style="max-width:100%;height:auto">'
        f'<text x="{pad_l}" y="20" font-size="13" font-weight="700" fill="#0f172a">{title}</text>'
        f"{axis}{''.join(bars)}</svg>"
    )


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
def _rows(results: list[ConfigResult]) -> list[dict[str, Any]]:
    out = []
    for r in results:
        s, u, p = r.metrics["security"], r.metrics["utility"], r.metrics["performance"]
        out.append(
            {
                "config": r.config.id,
                "name": r.config.name,
                "firewall": r.config.firewall,
                "trust": r.config.trust,
                "attack_success_rate": s["attack_success_rate"],
                "block_rate": s["block_rate"],
                "false_positive_rate": s["false_positive_rate"],
                "confirmation_rate": s["confirmation_rate"],
                "precision": s["precision"],
                "recall": s["recall"],
                "f1": s["f1"],
                "legitimate_task_completion": u["legitimate_task_completion"],
                "avg_turn_ms": p["avg_turn_ms"],
                "p95_turn_ms": p["p95_turn_ms"],
            }
        )
    return out


def render_markdown(
    rows: list[dict[str, Any]], fw: dict[str, Any], lat: dict[str, Any], overhead: dict[str, Any]
) -> str:
    L = [
        "# AegisAI — Phase 11 evaluation (four configurations)",
        "",
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · "
        f"rule-based brain · {rows[0]['config'] and ''}"
        f"{sum(1 for _ in rows)} configurations_",
        "",
        "Every labelled agent scenario was run through each configuration. The agent's"
        " policy gateway and output DLP are baseline hygiene (active everywhere); the"
        " two components toggled are the prompt-injection **Firewall** and the **Trust**"
        " engine. Decision classes follow ALLOW / CONFIRM / BLOCK (firewall FLAG =="
        " CONFIRM).",
        "",
        "## Security",
        "",
        "| Configuration | Firewall | Trust | Attack success ↓ | Block rate ↑ | "
        "False-positive ↓ | Precision | Recall | F1 |",
        "|---|:--:|:--:|--:|--:|--:|--:|--:|--:|",
    ]
    for r in rows:
        L.append(
            f"| {r['name']} | {'on' if r['firewall'] else 'off'} | "
            f"{'on' if r['trust'] else 'off'} | {_pct(r['attack_success_rate'])} | "
            f"{_pct(r['block_rate'])} | {_pct(r['false_positive_rate'])} | "
            f"{r['precision']:.2f} | {r['recall']:.2f} | {r['f1']:.2f} |"
        )
    L += [
        "",
        "## Utility & performance",
        "",
        "| Configuration | Legit-task completion ↑ | Confirmation rate | "
        "Avg turn (ms) | p95 turn (ms) |",
        "|---|--:|--:|--:|--:|",
    ]
    for r in rows:
        L.append(
            f"| {r['name']} | {_pct(r['legitimate_task_completion'])} | "
            f"{_pct(r['confirmation_rate'])} | {r['avg_turn_ms']} | {r['p95_turn_ms']} |"
        )
    L += [
        "",
        "### Overhead (vs. baseline)",
        "",
        f"- Combined adds **{overhead['ms']:.2f} ms/turn** "
        f"({overhead['pct']:.0f}%) over the agent-only baseline.",
        f"- Isolated firewall scan: p50 {lat['firewall_scan_ms']['p50']} ms, "
        f"p95 {lat['firewall_scan_ms']['p95']} ms.",
        f"- Isolated trust evaluation: p50 {lat['trust_evaluate_ms']['p50']} ms, "
        f"p95 {lat['trust_evaluate_ms']['p95']} ms.",
        "",
        "### Firewall component benchmark (labelled inputs)",
        "",
        f"On the {fw['cases']} labelled firewall inputs ({fw['malicious']} malicious, "
        f"{fw['benign']} benign): precision {fw['precision']:.1%}, recall "
        f"{fw['recall']:.1%}, F1 {fw['f1']:.3f}, FPR {fw['false_positive_rate']:.1%}, "
        f"scan latency p95 {fw['latency_ms']['p95']} ms.",
        "",
    ]
    return "\n".join(L) + "\n"


def render_html(
    rows: list[dict[str, Any]], lat: dict[str, Any], overhead: dict[str, Any]
) -> str:
    short = ["Baseline", "Trust", "Firewall", "Combined"][: len(rows)]
    charts = [
        _bar_chart("Attack success rate (lower is better)", short,
                   [r["attack_success_rate"] for r in rows], as_pct=True),
        _bar_chart("Block rate (higher is better)", short,
                   [r["block_rate"] for r in rows], as_pct=True),
        _bar_chart("False-positive rate (lower is better)", short,
                   [r["false_positive_rate"] for r in rows], as_pct=True),
        _bar_chart("Legit-task completion (higher is better)", short,
                   [r["legitimate_task_completion"] for r in rows], as_pct=True),
        _bar_chart("F1 score", short, [r["f1"] for r in rows], as_pct=True),
        _bar_chart("Avg turn latency (ms)", short,
                   [r["avg_turn_ms"] for r in rows], as_pct=False),
    ]  # fmt: skip

    def _trow(r: dict[str, Any]) -> str:
        return (
            f"<tr><td>{r['name']}</td>"
            f"<td>{'on' if r['firewall'] else 'off'}</td>"
            f"<td>{'on' if r['trust'] else 'off'}</td>"
            f"<td>{_pct(r['attack_success_rate'])}</td>"
            f"<td>{_pct(r['block_rate'])}</td>"
            f"<td>{_pct(r['false_positive_rate'])}</td>"
            f"<td>{_pct(r['legitimate_task_completion'])}</td>"
            f"<td>{r['f1']:.2f}</td>"
            f"<td>{r['avg_turn_ms']}</td></tr>"
        )

    gen = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AegisAI Phase 11 evaluation</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font: 15px/1.5 system-ui, sans-serif; margin: 0; background: #f8fafc; color: #0f172a; }}
  main {{ max-width: 1000px; margin: 0 auto; padding: 32px 20px 64px; }}
  h1 {{ font-size: 24px; margin: 0 0 4px; }}
  .sub {{ color: #64748b; margin: 0 0 24px; }}
  h2 {{ font-size: 17px; margin: 32px 0 12px;
        border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 14px; background: #fff;
           border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; }}
  th, td {{ padding: 8px 10px; text-align: right; border-bottom: 1px solid #f1f5f9; }}
  th:first-child, td:first-child {{ text-align: left; }}
  th {{ background: #f1f5f9; font-size: 12px; text-transform: uppercase;
       letter-spacing: .03em; color: #475569; }}
  .charts {{ display: grid; gap: 16px;
             grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }}
  .card {{ background: #fff; border: 1px solid #e2e8f0;
           border-radius: 10px; padding: 12px; }}
  .note {{ background: #fff; border: 1px solid #e2e8f0; border-left: 3px solid #0ea5e9;
           border-radius: 8px; padding: 12px 16px; color: #334155; font-size: 14px; }}
</style></head><body><main>
  <h1>AegisAI — Phase 11 evaluation</h1>
  <p class="sub">Four configurations · rule-based brain · generated {gen}</p>
  <p class="note">The agent policy gateway and output DLP are baseline hygiene (active in
  every configuration). The two components under study are the prompt-injection
  <strong>Firewall</strong> and the <strong>Trust</strong> engine. Decision classes follow
  the synopsis's ALLOW / CONFIRM / BLOCK taxonomy (firewall FLAG == CONFIRM).</p>

  <h2>Comparison charts</h2>
  <div class="charts">{"".join(f'<div class="card">{c}</div>' for c in charts)}</div>

  <h2>Summary table</h2>
  <table><thead><tr>
    <th>Configuration</th><th>FW</th><th>Trust</th><th>Attack success</th><th>Block rate</th>
    <th>False positive</th><th>Legit completion</th><th>F1</th><th>Avg ms</th>
  </tr></thead><tbody>{"".join(_trow(r) for r in rows)}</tbody></table>

  <h2>Performance</h2>
  <p class="note">Combined adds <strong>{overhead['ms']:.2f} ms/turn</strong>
  ({overhead['pct']:.0f}%) over the agent-only baseline.
  Isolated firewall scan p95 {lat['firewall_scan_ms']['p95']} ms;
  trust evaluation p95 {lat['trust_evaluate_ms']['p95']} ms.</p>
</main></body></html>
"""


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    headers = list(rows[0].keys())
    lines = [",".join(headers)]
    for r in rows:
        lines.append(",".join(str(r[h]) for h in headers))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 11 four-configuration experiment")
    parser.add_argument("--out", type=Path, default=ROOT / "evaluation" / "results")
    args = parser.parse_args(argv)
    configure_logging("CRITICAL")

    scenarios = _scenarios()
    # Warm up imports, graph construction and caches so the first configuration
    # isn't unfairly charged cold-start cost in the latency comparison.
    evaluate_config(CONFIGS[-1], scenarios, timing_repeats=1)
    results = [evaluate_config(cfg, scenarios) for cfg in CONFIGS]
    rows = _rows(results)
    lat = component_latency()
    fw = run_firewall_benchmark()

    by_id = {r["config"]: r for r in rows}
    base = by_id["baseline"]["avg_turn_ms"]
    comb = by_id["combined"]["avg_turn_ms"]
    overhead = {
        "ms": round(comb - base, 3),
        "pct": round((comb - base) / base * 100, 1) if base else 0.0,
    }

    args.out.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "configurations": rows,
        "overhead": overhead,
        "component_latency": lat,
        "firewall_benchmark": fw,
        "outcomes": {
            r.config.id: [o.__dict__ for o in r.outcomes] for r in results
        },
    }
    (args.out / "experiments.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    write_csv(rows, args.out / "comparison.csv")
    (args.out / "experiments.md").write_text(
        render_markdown(rows, fw, lat, overhead), encoding="utf-8"
    )
    (args.out / "experiments.html").write_text(
        render_html(rows, lat, overhead), encoding="utf-8"
    )

    print("Phase 11 — four-configuration comparison")
    print(f"{'config':<28}{'ASR':>7}{'block':>8}{'FPR':>7}{'legit':>8}{'F1':>7}{'ms':>9}")
    for r in rows:
        print(
            f"{r['name']:<28}{_pct(r['attack_success_rate']):>7}"
            f"{_pct(r['block_rate']):>8}{_pct(r['false_positive_rate']):>7}"
            f"{_pct(r['legitimate_task_completion']):>8}{r['f1']:>7.2f}{r['avg_turn_ms']:>9}"
        )
    print(f"\nOverhead (combined vs baseline): {overhead['ms']} ms/turn ({overhead['pct']}%)")
    print(f"Report: {args.out / 'experiments.md'}  |  {args.out / 'experiments.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

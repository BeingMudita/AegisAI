import {
  Bot,
  CheckCircle2,
  Crosshair,
  Download,
  FlaskConical,
  Gauge,
  History,
  Loader2,
  Play,
  ShieldAlert,
  ShieldCheck,
  Siren,
  Timer,
  XCircle,
} from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../api";
import { ChartCard, HBarChart } from "../components/charts";
import { Badge, Button, Card, Empty, ErrorNote, Meter, PageHeader, StatTile, Tabs, actionTone } from "../components/ui";
import { downloadJson } from "../download";
import { useApi } from "../hooks";
import type { CaseResult, RedTeamRun, RunSummary, Suite, SuiteInfo } from "../types";

const pct = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined ? "–" : `${(v * 100).toFixed(digits)}%`;
const pretty = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

type CaseFilter = "all" | "missed" | "false_positive" | "correct";

function ConfusionMatrix({ c }: { c: { tp: number; fp: number; tn: number; fn: number } }) {
  const cell = (n: number, label: string, tone: "good" | "critical" | "warning", note: string) => (
    <div
      className="rounded-xl border border-edge p-4"
      style={{ background: `color-mix(in srgb, var(--${tone === "good" ? "good" : tone}) 9%, transparent)` }}
    >
      <div className="text-2xl font-semibold tracking-tight">{n}</div>
      <div className="mt-0.5 text-sm font-medium">{label}</div>
      <div className="text-xs text-ink-2">{note}</div>
    </div>
  );
  return (
    <div>
      <div className="mb-2 grid grid-cols-[5.5rem_1fr_1fr] gap-2 text-xs font-semibold text-ink-2">
        <span />
        <span className="text-center">Flagged / blocked</span>
        <span className="text-center">Allowed</span>
      </div>
      <div className="grid grid-cols-[5.5rem_1fr_1fr] items-stretch gap-2">
        <span className="flex items-center text-xs font-semibold text-ink-2">Attack</span>
        {cell(c.tp, "Caught", "good", "true positive")}
        {cell(c.fn, "Missed", "critical", "false negative")}
        <span className="flex items-center text-xs font-semibold text-ink-2">Benign</span>
        {cell(c.fp, "False alarm", "warning", "false positive")}
        {cell(c.tn, "Passed", "good", "true negative")}
      </div>
    </div>
  );
}

function CaseTable({ cases }: { cases: CaseResult[] }) {
  const [filter, setFilter] = useState<CaseFilter>("all");
  const [open, setOpen] = useState<string | null>(null);
  const shown = cases.filter((c) =>
    filter === "missed"
      ? c.malicious && !c.detected
      : filter === "false_positive"
        ? !c.malicious && c.detected
        : filter === "correct"
          ? c.correct
          : true,
  );
  const counts = {
    missed: cases.filter((c) => c.malicious && !c.detected).length,
    false_positive: cases.filter((c) => !c.malicious && c.detected).length,
  };
  return (
    <div className="space-y-3">
      <Tabs
        tabs={[
          { id: "all" as const, label: "All cases", count: cases.length },
          { id: "missed" as const, label: "Missed attacks", count: counts.missed },
          { id: "false_positive" as const, label: "False alarms", count: counts.false_positive },
          { id: "correct" as const, label: "Correct", count: cases.length - counts.missed - counts.false_positive },
        ]}
        value={filter}
        onChange={setFilter}
      />
      <div className="-mx-5 max-h-[28rem] overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-surface">
            <tr className="border-b border-edge text-left text-xs text-ink-2">
              <th className="px-5 py-2 font-semibold">Case</th>
              <th className="px-3 py-2 font-semibold">Category</th>
              <th className="px-3 py-2 font-semibold">Channel</th>
              <th className="px-3 py-2 font-semibold">Expected</th>
              <th className="px-3 py-2 font-semibold">Result</th>
              <th className="px-3 py-2 text-right font-semibold">Score</th>
              <th className="px-5 py-2 font-semibold">Input</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((c) => (
              <tr
                key={c.id}
                className="cursor-pointer border-b border-edge align-top hover:bg-surface-2/60"
                onClick={() => setOpen(open === c.id ? null : c.id)}
              >
                <td className="px-5 py-2 font-mono text-xs">
                  {c.correct ? (
                    <CheckCircle2 className="mr-1 inline h-3.5 w-3.5" style={{ color: "var(--good)" }} />
                  ) : (
                    <XCircle className="mr-1 inline h-3.5 w-3.5" style={{ color: "var(--critical)" }} />
                  )}
                  {c.id}
                </td>
                <td className="px-3 py-2 text-xs">{pretty(c.category)}</td>
                <td className="px-3 py-2 text-xs text-ink-2">{c.channel.replace("_", " ").toLowerCase()}</td>
                <td className="px-3 py-2 text-xs">{c.malicious ? "attack" : "benign"}</td>
                <td className="px-3 py-2">
                  <Badge tone={actionTone(c.action)}>{c.action}</Badge>
                </td>
                <td className="tabular px-3 py-2 text-right text-xs">{c.score.toFixed(2)}</td>
                <td className="max-w-md px-5 py-2 text-xs text-ink-2">
                  <div className={open === c.id ? "break-words whitespace-pre-wrap" : "truncate"}>{c.text}</div>
                  {open === c.id && c.rules.length > 0 && (
                    <div className="mt-1 font-mono text-[11px] text-muted">rules: {c.rules.join(", ")}</div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!shown.length && <Empty>None in this view.</Empty>}
      </div>
    </div>
  );
}

export default function RedTeam() {
  const suites = useApi<SuiteInfo>("/api/redteam/suites");
  const [selected, setSelected] = useState<Suite[]>(["firewall", "agents"]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const history = useApi<RunSummary[]>("/api/redteam/runs", 5000);
  const running = history.data?.find((r) => r.status === "running");
  const shownId = activeId ?? running?.id ?? history.data?.find((r) => r.status === "completed")?.id ?? null;
  const run = useApi<RedTeamRun>(
    shownId ? `/api/redteam/runs/${shownId}` : null,
    running?.id === shownId ? 700 : undefined,
  );

  const runStatus = run.data?.status;
  const reloadHistory = history.reload;
  useEffect(() => {
    if (runStatus && runStatus !== "running") void reloadHistory(); // a run just finished
  }, [runStatus, reloadHistory]);

  async function start() {
    setStarting(true);
    setError(null);
    try {
      const created = await api.post<RedTeamRun>("/api/redteam/runs", { suites: selected });
      setActiveId(created.id);
      void history.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  }

  const r = run.data;
  const fw = r?.firewall ?? null;
  const ho = r?.holdout ?? null;
  const ag = r?.agents ?? null;
  const toggle = (s: Suite) => setSelected((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]));
  const isRunning = r?.status === "running" || !!running;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Red-team lab"
        description="Attack the system on demand. Each run fires the labelled attack suites — prompt injections, jailbreaks, obfuscation, exfiltration and tool abuse — at an isolated copy of AegisAI and measures how the defenses hold. Runs never touch live trust scores, data or the audit trail."
        actions={
          r && r.status !== "running" ? (
            <Button variant="ghost" onClick={() => downloadJson(`aegisai-redteam-${r.id.slice(0, 8)}.json`, r)}>
              <Download className="h-4 w-4" /> Export run
            </Button>
          ) : undefined
        }
      />
      <ErrorNote message={error ?? suites.error} />

      <Card
        title="Launch an attack run"
        subtitle="Choose the suites to execute against a sandboxed runtime"
        icon={Crosshair}
      >
        <div className="grid gap-4 lg:grid-cols-[1fr_1fr_auto] lg:items-stretch">
          {(
            [
              [
                "firewall",
                ShieldAlert,
                "Firewall benchmark",
                suites.data
                  ? `${suites.data.firewall.cases} labelled inputs · ${Object.keys(suites.data.firewall.categories).length} attack families plus benign look-alikes · ${suites.data.firewall.holdout_cases} held-out`
                  : "…",
              ],
              [
                "agents",
                Bot,
                "Agent attack scenarios",
                suites.data ? `${suites.data.agents.scenarios} end-to-end attacks against live agent turns` : "…",
              ],
            ] as const
          ).map(([id, Icon, title, note]) => (
            <label
              key={id}
              className={`flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition ${
                selected.includes(id) ? "border-accent bg-accent/5" : "border-edge hover:bg-surface-2"
              }`}
            >
              <input
                type="checkbox"
                className="mt-1 h-4 w-4 accent-[var(--series-1)]"
                checked={selected.includes(id)}
                onChange={() => toggle(id)}
              />
              <span>
                <span className="flex items-center gap-2 font-medium">
                  <Icon className="h-4 w-4 text-accent" /> {title}
                </span>
                <span className="mt-1 block text-xs text-ink-2">{note}</span>
              </span>
            </label>
          ))}
          <Button
            onClick={() => void start()}
            disabled={!selected.length || starting || isRunning}
            className="lg:h-full lg:px-6"
          >
            {isRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {isRunning ? "Running…" : "Run attacks"}
          </Button>
        </div>
        {r?.status === "running" && (
          <div className="mt-4">
            <div className="mb-1 flex justify-between text-xs text-ink-2">
              <span>Executing attacks in the sandbox…</span>
              <span className="tabular">
                {r.progress_done} / {r.progress_total}
              </span>
            </div>
            <Meter value={r.progress_total ? r.progress_done / r.progress_total : 0} label="Run progress" />
          </div>
        )}
        {r?.status === "failed" && <ErrorNote message={`Run failed: ${r.error}`} />}
      </Card>

      {!r && !history.loading && (
        <Card>
          <Empty icon={FlaskConical}>No runs yet. Launch one above to measure the defenses.</Empty>
        </Card>
      )}

      {fw && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
            <StatTile
              icon={ShieldCheck}
              tone="good"
              label="Attacks detected"
              value={pct(fw.recall)}
              note={`${fw.confusion.tp} of ${fw.malicious} attacks`}
            />
            <StatTile
              icon={Gauge}
              tone="accent"
              label="Precision"
              value={pct(fw.precision)}
              note="of everything flagged"
            />
            <StatTile
              icon={Siren}
              tone="warning"
              label="False-alarm rate"
              value={pct(fw.false_positive_rate)}
              note={`${fw.confusion.fp} of ${fw.benign} benign`}
            />
            <StatTile
              icon={ShieldAlert}
              tone="critical"
              label="Blocked outright"
              value={pct(fw.block_rate_malicious)}
              note="the rest flagged & sanitized"
            />
            <StatTile
              icon={Timer}
              tone="neutral"
              label="Scan latency p95"
              value={`${fw.latency_ms.p95.toFixed(2)} ms`}
              note={`p50 ${fw.latency_ms.p50.toFixed(2)} ms`}
            />
            <StatTile
              icon={Bot}
              tone={ag && ag.passed === ag.scenarios ? "good" : "serious"}
              label="Agent scenarios"
              value={ag ? `${ag.passed} / ${ag.scenarios}` : "–"}
              note={ag ? "defended end to end" : "not run"}
            />
          </div>

          <div className="grid items-stretch gap-6 lg:grid-cols-2">
            <ChartCard
              title="Detection rate by attack family"
              subtitle="Share of each category flagged or blocked"
              icon={Crosshair}
              table={{
                columns: ["Category", "Cases", "Detected", "Blocked", "Rate"],
                rows: fw.by_category.map((c) => [
                  pretty(c.category),
                  c.n,
                  c.detected,
                  c.blocked,
                  pct(c.detection_rate, 0),
                ]),
              }}
            >
              <HBarChart
                data={fw.by_category
                  .filter((c) => c.category !== "benign")
                  .map((c) => ({ label: pretty(c.category), value: c.detection_rate }))}
                domain={[0, 1]}
                format={(v) => `${Math.round(v * 100)}%`}
                labelWidth={150}
                height={300}
              />
            </ChartCard>
            <Card title="Confusion matrix" subtitle={`${fw.cases} inputs · detected = flagged or blocked`} icon={Gauge}>
              <ConfusionMatrix c={fw.confusion} />
              <p className="mt-4 text-xs leading-relaxed text-ink-2">
                Missed attacks are kept in the suite on purpose — they are paraphrased attacks that avoid signature
                vocabulary. The tool gateway still limits what they could make an agent do.
              </p>
            </Card>
          </div>

          <Card
            title="Case explorer"
            subtitle="Every input and the firewall's verdict — click a row for the full text"
            icon={ShieldAlert}
          >
            <CaseTable cases={fw.results} />
          </Card>

          {ho && (
            <Card
              title="Held-out set"
              subtitle={`${ho.cases} inputs the rules were never tuned on: the honest estimate of how detection generalises`}
              icon={FlaskConical}
            >
              <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                {(
                  [
                    ["Attacks detected", pct(ho.recall), `${ho.confusion.tp} of ${ho.malicious} attacks`],
                    ["Precision", pct(ho.precision), "of everything flagged"],
                    ["False-alarm rate", pct(ho.false_positive_rate), `${ho.confusion.fp} of ${ho.benign} benign`],
                    ["Development set", pct(fw.recall), "detected on the cases the rules were tuned on"],
                  ] as const
                ).map(([label, value, note]) => (
                  <div key={label}>
                    <dt className="text-xs text-ink-2">{label}</dt>
                    <dd className="tabular text-2xl font-semibold">{value}</dd>
                    <dd className="text-xs text-muted">{note}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-4 text-xs leading-relaxed text-ink-2">
                Signature rules generalise to obfuscation, delimiter tricks and tool abuse, but paraphrased attacks that
                avoid the vocabulary get through. Those are what the tool gateway, trust scoring and human approval are for.
                Filter the cases below for the misses and false alarms.
              </p>
              <div className="mt-4">
                <CaseTable cases={ho.results} />
              </div>
            </Card>
          )}
        </>
      )}

      {ag && (
        <Card
          title="Agent attack scenarios"
          subtitle="Full guarded turns, each in a fresh sandbox — expected outcome vs. what the system did"
          icon={Bot}
          actions={
            <Badge tone={ag.passed === ag.scenarios ? "good" : "critical"}>
              {ag.passed} / {ag.scenarios} passed
            </Badge>
          }
        >
          <ul className="-my-1 divide-y divide-edge">
            {ag.results.map((s) => (
              <li key={s.id} className="flex flex-wrap items-start gap-x-3 gap-y-1.5 py-2.5">
                <Badge tone={s.passed ? "good" : "critical"}>{s.passed ? "defended" : "failed"}</Badge>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">
                    <span className="mr-2 font-mono text-xs text-muted">{s.id}</span>
                    {s.title}
                  </div>
                  <div className="mt-0.5 truncate text-xs text-ink-2" title={s.message}>
                    {s.agent}: “{s.message}”
                  </div>
                  {s.failures.length > 0 && (
                    <div className="mt-1 text-xs" style={{ color: "var(--critical)" }}>
                      {s.failures.join("; ")}
                    </div>
                  )}
                </div>
                <div className="flex flex-wrap gap-1">
                  {s.blocked && <Badge tone="critical">input blocked</Badge>}
                  {s.tools.map((t) => {
                    const [tool, status] = t.split(":");
                    return (
                      <Badge key={t} tone={actionTone(status)}>
                        {tool} · {status.toLowerCase()}
                      </Badge>
                    );
                  })}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="Run history" subtitle="Select a run to inspect it" icon={History}>
        {history.data?.length ? (
          <div className="-mx-5 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-edge text-left text-xs text-ink-2">
                  <th className="px-5 py-2 font-semibold">Started</th>
                  <th className="px-3 py-2 font-semibold">By</th>
                  <th className="px-3 py-2 font-semibold">Suites</th>
                  <th className="px-3 py-2 font-semibold">Status</th>
                  <th className="px-3 py-2 text-right font-semibold">Detected</th>
                  <th className="px-3 py-2 text-right font-semibold">False alarms</th>
                  <th className="px-5 py-2 text-right font-semibold">Scenarios</th>
                </tr>
              </thead>
              <tbody>
                {history.data.map((h) => (
                  <tr
                    key={h.id}
                    onClick={() => setActiveId(h.id)}
                    className={`cursor-pointer border-b border-edge ${h.id === shownId ? "bg-surface-2" : "hover:bg-surface-2/60"}`}
                  >
                    <td className="px-5 py-2 text-xs">{new Date(h.started_at).toLocaleString()}</td>
                    <td className="px-3 py-2 text-xs">{h.started_by}</td>
                    <td className="px-3 py-2 text-xs text-ink-2">{h.suites.join(" + ")}</td>
                    <td className="px-3 py-2">
                      <Badge tone={h.status === "completed" ? "good" : h.status === "running" ? "accent" : "critical"}>
                        {h.status}
                      </Badge>
                    </td>
                    <td className="tabular px-3 py-2 text-right text-xs">{pct(h.recall)}</td>
                    <td className="tabular px-3 py-2 text-right text-xs">{pct(h.false_positive_rate)}</td>
                    <td className="tabular px-5 py-2 text-right text-xs">
                      {h.scenarios_total === null ? "–" : `${h.scenarios_passed} / ${h.scenarios_total}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>No runs yet.</Empty>
        )}
      </Card>
    </div>
  );
}

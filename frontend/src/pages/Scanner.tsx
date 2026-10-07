import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Database,
  Download,
  FileCode2,
  FlaskConical,
  Globe,
  Loader2,
  Play,
  ScanLine,
  ShieldCheck,
  Wrench,
  XCircle,
} from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../api";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorNote,
  PageHeader,
  toneVar,
  type Tone,
} from "../components/ui";
import { downloadText } from "../download";
import { useApi } from "../hooks";
import type {
  AgentInfo,
  RiskFinding,
  RiskSeverity,
  ScannerTestResult,
  SecurityReport,
} from "../types";

const RISK_TONE: Record<RiskSeverity, Tone> = { LOW: "good", MEDIUM: "warning", HIGH: "critical" };
const CATEGORY_ORDER = [
  "Prompt Injection",
  "Indirect Injection",
  "Excessive Tool Permission",
  "Sensitive Data Exposure",
  "Unsafe External Destinations",
  "Missing Human Approval",
  "Output Leakage",
];

function scoreTone(score: number): Tone {
  return score >= 80 ? "good" : score >= 60 ? "warning" : "critical";
}

function ScoreCard({ report }: { report: SecurityReport }) {
  const tone = scoreTone(report.score);
  const color = toneVar(tone);
  const p = report.profile;
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-6">
        <div
          className="flex h-28 w-28 shrink-0 flex-col items-center justify-center rounded-full border-4"
          style={{ borderColor: color }}
        >
          <span className="text-4xl font-bold tracking-tight" style={{ color }}>
            {report.score}
          </span>
          <span className="text-[11px] text-ink-2">/ 100 · {report.grade}</span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-xs font-semibold tracking-wide text-ink-2 uppercase">
            Agent security score
          </div>
          <div className="mt-0.5 text-lg font-semibold text-ink">{report.agent}</div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-ink-2">
            <span>discovered via {p.source}</span>
            <span>·</span>
            <span>LLM: {p.llm}</span>
            <Badge tone={p.aegis_integrated ? "good" : "critical"}>
              {p.aegis_integrated ? "AegisAI-protected" : "not behind AegisAI"}
            </Badge>
          </div>
        </div>
      </div>
    </Card>
  );
}

function RiskTable({ findings }: { findings: RiskFinding[] }) {
  const by = new Map(findings.map((f) => [f.category, f]));
  return (
    <Card title="Risk assessment" subtitle="Seven categories mapped to the OWASP LLM Top 10" icon={ShieldCheck}>
      <ul className="divide-y divide-edge">
        {CATEGORY_ORDER.map((cat) => {
          const f = by.get(cat);
          if (!f) return null;
          return (
            <li key={cat} className="flex items-center gap-3 py-2.5">
              <span className="min-w-0 flex-1 text-sm font-medium text-ink">{cat}</span>
              {f.owasp && <span className="font-mono text-[11px] text-muted">{f.owasp}</span>}
              <Badge tone={RISK_TONE[f.severity]}>{f.severity}</Badge>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function Fixes({ findings }: { findings: RiskFinding[] }) {
  const fixes = findings.filter((f) => f.fix && f.severity !== "LOW");
  if (!fixes.length)
    return (
      <Card title="Recommended fixes" icon={Wrench}>
        <Empty icon={CheckCircle2}>No high-priority fixes — this agent is well configured.</Empty>
      </Card>
    );
  return (
    <Card title="Recommended fixes" subtitle="Apply these to raise the score" icon={Wrench}>
      <div className="space-y-4">
        {fixes.map((f) => (
          <div key={f.category}>
            <div className="flex items-center gap-2">
              <Badge tone={RISK_TONE[f.severity]}>{f.severity}</Badge>
              <span className="text-sm font-semibold text-ink">{f.category}</span>
            </div>
            <p className="mt-1 text-sm text-ink-2">{f.detail}</p>
            <pre className="mt-2 overflow-x-auto rounded-lg border border-edge bg-surface-2/60 p-3 font-mono text-[12px] leading-relaxed text-ink">
              {f.fix}
            </pre>
          </div>
        ))}
      </div>
    </Card>
  );
}

function riskBorder(risk: string): string {
  return risk === "HIGH" ? "var(--critical)" : risk === "MEDIUM" ? "var(--warning)" : "var(--border)";
}

function PermissionGraph({ report }: { report: SecurityReport }) {
  const p = report.profile;
  const col = "flex-1 min-w-[180px] space-y-2";
  return (
    <Card title="Permission graph" subtitle="What the agent can reach, and where data can flow" icon={ScanLine}>
      <div className="flex flex-wrap items-start gap-4">
        <div className={col}>
          <div className="eyebrow flex items-center gap-1.5">
            <Wrench className="h-3.5 w-3.5" /> Tools
          </div>
          {p.tools.map((t) => (
            <div
              key={t.name}
              className="rounded-lg border p-2.5"
              style={{ borderColor: t.risk_level === "HIGH" || t.risk_level === "CRITICAL" ? "var(--critical)" : "var(--border)" }}
            >
              <div className="font-mono text-xs font-semibold text-ink">{t.name}</div>
              <div className="mt-1 flex flex-wrap gap-1">
                <Badge tone={t.risk_level === "LOW" ? "good" : t.risk_level === "MEDIUM" ? "warning" : "critical"}>
                  {t.risk_level}
                </Badge>
                {t.external && <Badge tone="warning">external:{t.domain_kind ?? "url"}</Badge>}
                {t.requires_approval && <Badge tone="good">approval</Badge>}
              </div>
            </div>
          ))}
        </div>
        <div className={col}>
          <div className="eyebrow flex items-center gap-1.5">
            <Database className="h-3.5 w-3.5" /> Data sources
          </div>
          {p.data_sources.length ? (
            p.data_sources.map((d) => (
              <div key={d.name} className="rounded-lg border border-edge p-2.5 text-sm">
                {d.name}
                {d.untrusted && (
                  <Badge tone="warning">
                    <AlertTriangle className="h-3 w-3" /> untrusted
                  </Badge>
                )}
              </div>
            ))
          ) : (
            <p className="text-xs text-muted">None</p>
          )}
          <div className="eyebrow mt-3 flex items-center gap-1.5">
            <Globe className="h-3.5 w-3.5" /> External destinations
          </div>
          {p.external_destinations.length ? (
            p.external_destinations.map((e) => (
              <div key={e} className="rounded-lg border border-edge p-2.5 font-mono text-xs">
                {e}
              </div>
            ))
          ) : (
            <p className="text-xs text-muted">None</p>
          )}
        </div>
      </div>
      {p.data_flows.length > 0 && (
        <div className="mt-4">
          <div className="eyebrow mb-2">Data flows</div>
          <ul className="space-y-1.5">
            {p.data_flows.map((fl) => (
              <li
                key={fl.label}
                className="flex items-center gap-2 rounded-lg border-l-2 bg-surface-2/50 px-3 py-2 text-sm"
                style={{ borderColor: riskBorder(fl.risk) }}
              >
                <span className="min-w-0 flex-1 break-words">{fl.label}</span>
                <Badge tone={RISK_TONE[fl.risk as RiskSeverity]}>{fl.risk}</Badge>
              </li>
            ))}
          </ul>
        </div>
      )}
      {p.notes.length > 0 && (
        <ul className="mt-4 space-y-1 text-xs text-ink-2">
          {p.notes.map((n) => (
            <li key={n}>• {n}</li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function PolicyTest({ agent }: { agent: string }) {
  const [state, setState] = useState<{ loading: boolean; result: ScannerTestResult | null; error: string | null }>({
    loading: false,
    result: null,
    error: null,
  });
  useEffect(() => setState({ loading: false, result: null, error: null }), [agent]);

  async function run() {
    setState({ loading: true, result: null, error: null });
    try {
      const result = await api.post<ScannerTestResult>(`/api/scanner/agents/${agent}/test`, {});
      setState({ loading: false, result, error: null });
    } catch (e) {
      setState({ loading: false, result: null, error: e instanceof Error ? e.message : String(e) });
    }
  }

  return (
    <Card
      title="Red-team the policy"
      subtitle="Run the attack scenarios for this agent against an isolated sandbox"
      icon={FlaskConical}
      actions={
        <Button onClick={() => void run()} disabled={state.loading}>
          {state.loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          {state.loading ? "Running…" : "Run policy test"}
        </Button>
      }
    >
      <ErrorNote message={state.error} />
      {state.result ? (
        <div className="space-y-3">
          <Badge tone={state.result.passed === state.result.total ? "good" : "critical"}>
            {state.result.passed} / {state.result.total} scenarios defended
          </Badge>
          <ul className="divide-y divide-edge">
            {state.result.scenarios.map((s) => (
              <li key={s.id} className="flex items-start gap-2 py-2 text-sm">
                {s.passed ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" style={{ color: "var(--good)" }} />
                ) : (
                  <XCircle className="mt-0.5 h-4 w-4 shrink-0" style={{ color: "var(--critical)" }} />
                )}
                <span className="min-w-0">
                  <span className="mr-2 font-mono text-xs text-muted">{s.id}</span>
                  {s.title}
                  {s.failures.length > 0 && (
                    <span className="block text-xs" style={{ color: "var(--critical)" }}>
                      {s.failures.join("; ")}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        !state.loading && <Empty icon={FlaskConical}>Run the test to validate the policy end to end.</Empty>
      )}
    </Card>
  );
}

export default function Scanner() {
  const agents = useApi<AgentInfo[]>("/api/agents");
  const [selected, setSelected] = useState<string | null>(null);
  const agent = selected ?? agents.data?.[0]?.name ?? null;
  const report = useApi<SecurityReport>(agent ? `/api/scanner/agents/${agent}/report` : null);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Agent security scanner"
        description="Point AegisAI at an agent and it builds a security profile — tools, data sources, external destinations, permissions and data flows — scores it against the OWASP LLM Top 10, and generates a least-privilege policy you can red-team. Discover → Assess → Configure → Test."
      />
      <ErrorNote message={agents.error ?? report.error} />

      <div className="flex flex-wrap gap-2">
        {agents.data?.map((a) => (
          <button
            key={a.name}
            onClick={() => setSelected(a.name)}
            aria-current={a.name === agent ? "true" : undefined}
            className={`flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm transition ${
              a.name === agent ? "border-accent bg-accent/5 font-semibold" : "border-edge hover:bg-surface-2"
            }`}
          >
            <Bot className="h-4 w-4 text-accent" /> {a.name}
          </button>
        ))}
      </div>

      {!report.data ? (
        <Card>
          <Empty icon={ScanLine}>{report.loading ? "Scanning…" : "Pick an agent to scan."}</Empty>
        </Card>
      ) : (
        <>
          <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
            <ScoreCard report={report.data} />
            <RiskTable findings={report.data.findings} />
          </div>
          <PermissionGraph report={report.data} />
          <Fixes findings={report.data.findings} />
          <Card
            title="Generated policy"
            subtitle="A least-privilege aegis.yaml for this agent"
            icon={FileCode2}
            actions={
              <Button
                variant="ghost"
                size="sm"
                onClick={() => downloadText(`aegis-${report.data!.agent}.yaml`, report.data!.generated_policy, "text/yaml")}
              >
                <Download className="h-3.5 w-3.5" /> Download
              </Button>
            }
          >
            <pre className="overflow-x-auto rounded-lg border border-edge bg-surface-2/60 p-3 font-mono text-[12px] leading-relaxed text-ink">
              {report.data.generated_policy}
            </pre>
          </Card>
          {agent && <PolicyTest agent={agent} />}
        </>
      )}
    </div>
  );
}

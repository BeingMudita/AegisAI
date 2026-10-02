import {
  Activity,
  BarChart3,
  Bot,
  Database,
  Gauge,
  ScanSearch,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  Siren,
  Workflow,
} from "lucide-react";

import { ChartCard, DecisionChart, HBarChart } from "../components/charts";
import { PipelineFlow, type Stage } from "../components/pipeline";
import {
  Badge,
  Card,
  Empty,
  ErrorNote,
  Meter,
  PageHeader,
  StatTile,
  formatNumber,
  severityTone,
  toneVar,
  trustTone,
} from "../components/ui";
import { formatTime, useApi } from "../hooks";
import type { AgentInfo, KbStats, SecurityEvent, TelemetrySummary } from "../types";

const SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"] as const;
const pretty = (s: string) =>
  s
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/^\w/, (c) => c.toUpperCase());
const CHART_HEIGHT = 240;

export default function Overview() {
  const summary = useApi<TelemetrySummary>("/api/security-events/summary", 3000);
  const agents = useApi<AgentInfo[]>("/api/agents", 3000);
  const kb = useApi<KbStats>("/api/retrieval", 10000);
  const recent = useApi<{ events: SecurityEvent[] }>("/api/security-events?limit=7", 3000);
  const trust = useApi<{ threshold: number }>("/api/trust");

  const s = summary.data;
  const decisions = s?.decisions ?? [];
  const d = (component: string) => decisions.find((x) => x.component === component) ?? { allowed: 0, denied: 0 };
  const byType = Object.entries(s?.by_type ?? {})
    .map(([label, value]) => ({ label: pretty(label), value }))
    .sort((a, b) => b.value - a.value);
  const bySeverity = SEVERITIES.map((sev) => ({ label: pretty(sev), value: s?.by_severity[sev] ?? 0, sev }));
  const threshold = trust.data?.threshold ?? 0.6;
  const agentTrust = (agents.data ?? []).map((a) => ({ label: a.name, value: a.trust_score }));

  const stage = (id: string, label: string, icon: Stage["icon"], component: string, what: string): Stage => {
    const x = d(component);
    return {
      id,
      label,
      icon,
      tone: x.denied ? "warning" : "accent",
      value: `${formatNumber(x.allowed + x.denied)} checks`,
      detail: (
        <>
          {what}
          <br />
          <span className="tabular">
            {formatNumber(x.allowed)} passed ·{" "}
            <span style={x.denied ? { color: "var(--critical)" } : undefined}>{formatNumber(x.denied)} stopped</span>
          </span>
        </>
      ),
    };
  };

  const stages: Stage[] = [
    stage("ingest", "Data ingestion", Database, "ingestion", "documents screened chunk by chunk"),
    stage("firewall", "Injection firewall", ShieldCheck, "firewall", "input, retrieved text & tool output"),
    stage("rag", "Guarded retrieval", ScanSearch, "rag", "untrusted sources filtered"),
    stage("policy", "Policy check", Workflow, "policy", "allowed tools & domains"),
    stage("trust", "Trust check", Gauge, "trust", "agent trust ≥ tool's bar"),
    stage("tools", "Tool gateway", Bot, "tools", "final allow / deny"),
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Security overview"
        description="Everything an agent receives or does passes through these checkpoints. Counts update live — try an attack in the Agent console or upload a document in Data & RAG and watch them move."
      />
      <ErrorNote message={summary.error} />

      <Card
        title="How every request is protected"
        subtitle="Live counts per checkpoint since the server started"
        icon={Workflow}
      >
        <PipelineFlow stages={stages} />
      </Card>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile
          icon={Siren}
          tone="serious"
          label="Security events"
          value={formatNumber(s?.total_events ?? 0)}
          note="incidents recorded"
        />
        <StatTile
          icon={ShieldX}
          tone="critical"
          label="Injection detections"
          value={formatNumber(s?.by_type.PROMPT_INJECTION ?? 0)}
          note="flagged or blocked text"
        />
        <StatTile
          icon={ShieldAlert}
          tone="warning"
          label="Policy violations"
          value={formatNumber(s?.by_type.POLICY_VIOLATION ?? 0)}
          note="forbidden tools / domains"
        />
        <StatTile
          icon={Database}
          tone="accent"
          label="Quarantined chunks"
          value={formatNumber(kb.data?.chunks_quarantined ?? 0)}
          note={kb.data ? `${formatNumber(kb.data.chunks_indexed)} chunks indexed` : undefined}
        />
      </div>

      <div className="grid items-stretch gap-6 lg:grid-cols-2">
        <ChartCard
          title="Decisions by checkpoint"
          subtitle="Allowed vs denied at each security layer"
          icon={BarChart3}
          table={{
            columns: ["Checkpoint", "Allowed", "Denied"],
            rows: decisions.map((x) => [x.component, x.allowed, x.denied]),
          }}
        >
          {decisions.length ? (
            <DecisionChart data={decisions} height={CHART_HEIGHT} />
          ) : (
            <Empty icon={BarChart3}>No decisions yet — try the agent console.</Empty>
          )}
        </ChartCard>

        <ChartCard
          title="Events by severity"
          subtitle="How serious the recorded incidents are"
          icon={Siren}
          table={{ columns: ["Severity", "Count"], rows: bySeverity.map((x) => [x.label, x.value]) }}
        >
          {s?.total_events ? (
            <HBarChart
              data={bySeverity}
              colors={bySeverity.map((x) => toneVar(severityTone(x.sev)))}
              labelWidth={80}
              height={CHART_HEIGHT}
            />
          ) : (
            <Empty icon={Siren}>No security events recorded.</Empty>
          )}
        </ChartCard>

        <ChartCard
          title="Events by type"
          subtitle="What kind of attacks and violations were seen"
          icon={Activity}
          table={{ columns: ["Type", "Count"], rows: byType.map((x) => [x.label, x.value]) }}
        >
          {byType.length ? (
            <HBarChart data={byType} labelWidth={140} height={CHART_HEIGHT} />
          ) : (
            <Empty icon={Activity}>No security events recorded.</Empty>
          )}
        </ChartCard>

        <ChartCard
          title="Agent trust"
          subtitle={`Attacks lower it · line = ${threshold.toFixed(2)} threshold`}
          icon={Gauge}
          table={{
            columns: ["Agent", "Trust", "Level"],
            rows: (agents.data ?? []).map((a) => [a.name, a.trust_score.toFixed(2), a.trust_level]),
          }}
        >
          {agentTrust.length ? (
            <HBarChart
              data={agentTrust}
              domain={[0, 1]}
              format={(v) => v.toFixed(2)}
              reference={{ at: threshold, label: "threshold" }}
              labelWidth={110}
              height={CHART_HEIGHT}
            />
          ) : (
            <Empty icon={Gauge}>No agents.</Empty>
          )}
        </ChartCard>
      </div>

      <div className="grid items-stretch gap-6 lg:grid-cols-3">
        <Card
          title="Latest events"
          subtitle="Newest first — full log in Security events"
          icon={Siren}
          className="lg:col-span-2"
        >
          {recent.data?.events.length ? (
            <ul className="-my-2 divide-y divide-edge">
              {recent.data.events.map((e) => (
                <li key={e.id} className="flex items-start gap-3 py-2.5 text-sm">
                  <span className="tabular w-20 shrink-0 pt-0.5 text-xs text-muted">{formatTime(e.created_at)}</span>
                  <span className="w-20 shrink-0">
                    <Badge tone={severityTone(e.severity)}>{e.severity.toLowerCase()}</Badge>
                  </span>
                  <span className="min-w-0 flex-1 text-ink">{e.description}</span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty icon={ShieldCheck}>Nothing yet — all quiet.</Empty>
          )}
        </Card>
        <Card title="Agents" subtitle="Current standing" icon={Bot}>
          <ul className="space-y-4">
            {(agents.data ?? []).map((a) => (
              <li key={a.name}>
                <div className="mb-1.5 flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{a.name}</span>
                  <Badge tone={trustTone(a.trust_level)}>{a.trust_level.toLowerCase()}</Badge>
                </div>
                <div className="flex items-center gap-2">
                  <Meter
                    value={a.trust_score}
                    markers={[{ at: threshold, label: `threshold ${threshold}` }]}
                    label={`${a.name} trust`}
                  />
                  <span className="tabular w-9 text-right text-xs text-ink-2">{a.trust_score.toFixed(2)}</span>
                </div>
                <div className="mt-1.5 text-xs text-muted">
                  {a.allowed_tools.length} tools allowed · {a.allowed_domains.join(", ") || "no web access"}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}

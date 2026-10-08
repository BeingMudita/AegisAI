import { Activity, ArrowRight, Bot, Database, RefreshCw, ShieldCheck, ShieldX } from "lucide-react";
import { isStaff, useAuth } from "../auth";
import { ChartCard, DecisionChart, DonutChart, HBarChart } from "../components/charts";
import { Badge, Button, Card, Empty, ErrorNote, PageHeader, StatTile, severityTone } from "../components/ui";
import { formatTime, useApi } from "../hooks";
import type { AgentInfo, KbStats, SecurityEvent, TelemetrySummary } from "../types";

export default function Overview() {
  const { user } = useAuth();
  const staff = isStaff(user);
  const summary = useApi<TelemetrySummary>(staff ? "/api/security-events/summary" : null, 5000);
  const agents = useApi<AgentInfo[]>("/api/agents", 5000);
  const kb = useApi<KbStats>("/api/retrieval", 10000);
  const recent = useApi<{ events: SecurityEvent[] }>(staff ? "/api/security-events?limit=6" : null, 5000);
  const data = summary.data;
  const error = agents.error ?? kb.error ?? summary.error ?? recent.error;
  const decisions = data?.decisions ?? [];

  const k = kb.data;
  const clean = Math.max(0, (k?.chunks_indexed ?? 0) - (k?.chunks_flagged ?? 0));
  const composition = [
    { label: "Indexed (clean)", value: clean, color: "var(--brand)" },
    { label: "Sanitized", value: k?.chunks_flagged ?? 0, color: "var(--warning)" },
    { label: "Quarantined", value: k?.chunks_quarantined ?? 0, color: "var(--critical)" },
  ].filter((d) => d.value > 0);

  const trust = (agents.data ?? []).map((a) => ({ label: a.name, value: a.trust_score }));
  const sources = (k?.source_summaries ?? []).map((s) => ({ label: s.source, value: s.trust_score }));
  const severities = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
    .map((l) => ({ label: l.toLowerCase(), value: data?.by_severity[l] ?? 0 }))
    .filter((s) => s.value > 0);

  const status = error
    ? "Connection needs attention"
    : agents.loading
      ? "Connecting…"
      : "Auto-refresh enabled · counts since server start";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Workspace overview"
        description="Your control center for safer agent operations."
        actions={
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              void agents.reload();
              void kb.reload();
              void summary.reload();
              void recent.reload();
            }}
          >
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </Button>
        }
      />
      <ErrorNote message={error ? `${error} Displayed values may be out of date. Refresh to reconnect.` : null} />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-heading text-lg font-semibold text-ink">Operational snapshot</h2>
        <span className="text-xs text-ink-2">{status}</span>
      </div>
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <StatTile label="Available agents" value={agents.data?.length ?? "—"} note="Governed by individual policies" icon={Bot} />
        <StatTile
          label="Indexed chunks"
          value={k?.chunks_indexed.toLocaleString() ?? "—"}
          note={k ? `${k.documents} documents in knowledge base` : "Waiting for knowledge base"}
          icon={Database}
        />
        <StatTile label="Quarantined chunks" value={k?.chunks_quarantined.toLocaleString() ?? "—"} note="Withheld from retrieval" icon={ShieldX} tone="warning" />
        <StatTile
          label={staff ? "Security events" : "Flagged chunks"}
          value={staff ? (data?.total_events.toLocaleString() ?? "—") : (k?.chunks_flagged ?? "—")}
          note={staff ? "Investigate in the event log" : "Sanitized during ingestion"}
          icon={Activity}
          tone="serious"
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <ChartCard
          title="Knowledge composition"
          subtitle="How every screened chunk resolved"
          icon={Database}
          table={{ columns: ["State", "Chunks"], rows: composition.map((c) => [c.label, c.value]) }}
        >
          {composition.length ? (
            <DonutChart data={composition} unit="chunks" />
          ) : (
            <Empty icon={Database}>{kb.loading ? "Loading knowledge base…" : "No chunks indexed yet."}</Empty>
          )}
        </ChartCard>

        <ChartCard
          title="Agent trust"
          subtitle="Trust gates which capabilities each agent can use"
          icon={ShieldCheck}
          table={{ columns: ["Agent", "Trust"], rows: trust.map((t) => [t.label, t.value.toFixed(2)]) }}
        >
          {trust.length ? (
            <HBarChart data={trust} domain={[0, 1]} format={(v) => v.toFixed(2)} labelWidth={120} height={Math.max(160, trust.length * 48)} />
          ) : (
            <Empty icon={Bot}>{agents.loading ? "Loading agents…" : "No agents available."}</Empty>
          )}
        </ChartCard>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <ChartCard
          title="Source trust"
          subtitle="A source that serves injected content drops below the 0.30 retrieval cut-off"
          icon={Database}
          table={{ columns: ["Source", "Trust"], rows: sources.map((s) => [s.label, s.value.toFixed(2)]) }}
        >
          {sources.length ? (
            <HBarChart
              data={sources}
              domain={[0, 1]}
              format={(v) => v.toFixed(2)}
              reference={{ at: 0.3, label: "cut-off" }}
              labelWidth={150}
              height={Math.max(160, sources.length * 40)}
            />
          ) : (
            <Empty icon={Database}>No sources yet.</Empty>
          )}
        </ChartCard>

        {staff && (
          <ChartCard
            title="Security decisions"
            subtitle="Allowed and denied at each checkpoint"
            icon={ShieldCheck}
            table={{ columns: ["Checkpoint", "Allowed", "Denied"], rows: decisions.map((d) => [d.component, d.allowed, d.denied]) }}
          >
            {decisions.length ? (
              <DecisionChart data={decisions} height={240} />
            ) : severities.length ? (
              <DonutChart
                data={severities.map((s) => ({ label: s.label, value: s.value, color: `var(--${severityColorVar(s.label)})` }))}
                unit="events"
              />
            ) : (
              <Empty icon={ShieldCheck}>
                No guarded requests yet — run one in the Agent workspace and decisions will appear here.
              </Empty>
            )}
          </ChartCard>
        )}
      </div>

      {staff && (
        <Card
          title="Recent security events"
          subtitle="The latest entries from the audit log"
          icon={Activity}
          actions={
            <a className="action-link" href="#/events">
              View all events <ArrowRight className="h-4 w-4" />
            </a>
          }
        >
          {recent.data?.events.length ? (
            <ul className="divide-y divide-edge">
              {recent.data.events.map((e) => (
                <li key={e.id} className="flex flex-wrap items-start gap-3 py-3 text-sm">
                  <span className="w-20 text-xs text-ink-2">{formatTime(e.created_at)}</span>
                  <Badge tone={severityTone(e.severity)}>{e.severity.toLowerCase()}</Badge>
                  <span className="min-w-[160px] flex-1">{e.description}</span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty icon={ShieldCheck}>
              {recent.loading
                ? "Loading events…"
                : recent.error
                  ? "Event data is unavailable."
                  : "No incidents recorded. Run a request in the Agent workspace or launch the Red-team lab to generate events."}
            </Empty>
          )}
        </Card>
      )}
    </div>
  );
}

function severityColorVar(label: string): string {
  return { critical: "critical", high: "serious", medium: "warning", low: "brand", info: "muted" }[label] ?? "muted";
}

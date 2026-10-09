import { ArrowRight, Bot, Database, Network, ShieldCheck, ShieldX, Activity, RefreshCw } from "lucide-react";
import { isStaff, useAuth } from "../auth";
import { ChartCard, DecisionChart, HBarChart } from "../components/charts";
import ArchiveExplorer from "../components/archive/ArchiveExplorer";
import { Badge, Button, Card, Empty, ErrorNote, Meter, PageHeader, StatTile, severityTone, trustTone } from "../components/ui";
import { formatTime, useApi } from "../hooks";
import type { AgentInfo, KbStats, SecurityEvent, TelemetrySummary } from "../types";

export default function Overview() {
  const { user } = useAuth();
  const staff = isStaff(user);
  const summary = useApi<TelemetrySummary>(staff ? "/api/security-events/summary" : null, 5000);
  const agents = useApi<AgentInfo[]>("/api/agents", 5000);
  const kb = useApi<KbStats>("/api/retrieval?include_sources=false", 10000);
  const recent = useApi<{ events: SecurityEvent[] }>(staff ? "/api/security-events?limit=5" : null, 5000);
  const data = summary.data;
  const error = agents.error ?? kb.error ?? summary.error ?? recent.error;
  const decisions = data?.decisions ?? [];
  const eventTypes = Object.entries(data?.by_type ?? {}).map(([label, value]) => ({ label: label.replaceAll("_", " ").toLowerCase(), value }));
  const severities = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"].map(label => ({ label: label.toLowerCase(), value: data?.by_severity[label] ?? 0 }));
  const standings = (agents.data ?? []).map(a => ({ label: a.name, value: a.trust_score }));
  return <div className="space-y-6">
    <PageHeader title="Workspace overview" description="Your control center for safer agent operations." actions={<Button variant="ghost" size="sm" onClick={() => { void agents.reload(); void kb.reload(); void summary.reload(); void recent.reload(); }}><RefreshCw className="h-3.5 w-3.5" /> Refresh</Button>} />
    <ErrorNote message={error ? `${error} Displayed values may be out of date. Refresh to reconnect.` : null} />
    {staff ? <ArchiveExplorer /> : <Card title="Knowledge explorer"><p className="text-sm text-ink-2">Document structure and stored passages are available to administrators and security analysts.</p><a className="action-link mt-4" href="#/console">Start a guarded request <ArrowRight className="h-4 w-4" /></a></Card>}
    <details className="rounded-xl border border-edge bg-surface p-5" open={!staff}>
    <summary className="text-sm font-semibold">Security & agent activity</summary>
    <div className="mt-5 space-y-6">
    <div className="flex flex-wrap items-center justify-between gap-2 pt-3"><h2 className="text-base font-semibold">Operational snapshot</h2><span className="text-xs text-ink-2">{error ? "Connection needs attention" : agents.loading ? "Connecting…" : "Auto-refresh enabled"} · counts since server start</span></div>
    <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
      <StatTile label="Available agents" value={agents.data?.length ?? "—"} note="Governed by individual policies" icon={Bot} />
      <StatTile label="Indexed chunks" value={kb.data?.chunks_indexed.toLocaleString() ?? "—"} note={kb.data ? `${kb.data.documents} documents in knowledge base` : "Waiting for knowledge base"} icon={Database} />
      <StatTile label="Quarantined chunks" value={kb.data?.chunks_quarantined.toLocaleString() ?? "—"} note="Withheld from retrieval" icon={ShieldX} tone="warning" />
      <StatTile label={staff ? "Security events" : "Flagged chunks"} value={staff ? data?.total_events.toLocaleString() ?? "—" : kb.data?.chunks_flagged ?? "—"} note={staff ? "Investigate in the event log" : "Sanitized during ingestion"} icon={Activity} tone="serious" />
    </div>
    <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
      {staff ? <ChartCard title="Security decisions" subtitle="Allowed and denied at each checkpoint" table={{ columns: ["Checkpoint", "Allowed", "Denied"], rows: decisions.map(d => [d.component, d.allowed, d.denied]) }}>{decisions.length ? <DecisionChart data={decisions} height={245} /> : <Empty icon={ShieldCheck}>{summary.loading ? "Loading decisions…" : summary.error ? "Decision data is unavailable." : "Run a request to see security decisions here."}</Empty>}</ChartCard> : <Card title="Understand the security boundaries" icon={Network}><p className="text-sm leading-relaxed text-ink-2">Explore the interactive system map to see how documents, agent decisions, and tools are connected. Each component includes its responsibility and current implementation limits.</p><a className="action-link mt-6" href="#/architecture">Open architecture <ArrowRight className="h-4 w-4" /></a></Card>}
      <Card title="Agent readiness" subtitle="Trust controls which capabilities an agent can use" actions={staff ? <a className="action-link" href="#/trust">Manage trust <ArrowRight className="h-3 w-3" /></a> : undefined}>
        <ul className="divide-y divide-edge">{agents.data?.map(a => <li key={a.name} className="py-4 first:pt-0"><div className="mb-3 flex flex-wrap items-center justify-between gap-2"><strong className="text-sm">{a.name}</strong><Badge tone={trustTone(a.trust_level)}>{a.trust_score.toFixed(2)} · {a.trust_level.toLowerCase()}</Badge></div><Meter value={a.trust_score} tone={trustTone(a.trust_level)} label={`${a.name} trust`} /><p className="mt-2 text-xs text-ink-2">{a.allowed_tools.length} allowed tools · {a.allowed_domains.length} approved domains</p></li>)}</ul>
        {!agents.data && <Empty>{agents.error ? "Agent status unavailable." : "Loading agents…"}</Empty>}
        <p className="border-t border-edge pt-3 text-xs leading-relaxed text-ink-2">Tool requirements vary. An agent may answer questions while higher-risk actions remain restricted.</p>
      </Card>
    </div>
    {staff && <Card title="Recent security events" subtitle="Use the event log to inspect context and export evidence" actions={<a className="action-link" href="#/events">View all events <ArrowRight className="h-4 w-4" /></a>}>
      {recent.data?.events.length ? <ul className="divide-y divide-edge">{recent.data.events.map(e => <li key={e.id} className="flex flex-wrap items-start gap-3 py-3 text-sm"><span className="w-20 text-xs text-ink-2">{formatTime(e.created_at)}</span><Badge tone={severityTone(e.severity)}>{e.severity.toLowerCase()}</Badge><span className="min-w-[160px] flex-1">{e.description}</span></li>)}</ul> : <Empty icon={ShieldCheck}>{recent.loading ? "Loading events…" : recent.error ? "Event data is unavailable." : "No incidents recorded. Your next guarded request will appear in the decision counts."}</Empty>}
    </Card>}
    {staff && <details className="rounded-xl border border-edge bg-surface p-5">
      <summary className="text-sm font-semibold">Detailed analytics · event types, severity, and trust</summary>
      <div className="mt-5 grid gap-4 xl:grid-cols-3">
        <ChartCard title="Events by type" table={{columns:["Type", "Count"], rows:eventTypes.map(x => [x.label, x.value])}}>{eventTypes.length ? <HBarChart data={eventTypes} labelWidth={130} height={240} /> : <Empty>No event types recorded.</Empty>}</ChartCard>
        <ChartCard title="Events by severity" table={{columns:["Severity", "Count"], rows:severities.map(x => [x.label, x.value])}}><HBarChart data={severities} labelWidth={70} height={240} /></ChartCard>
        <ChartCard title="Agent trust" table={{columns:["Agent", "Trust"], rows:standings.map(x => [x.label, x.value.toFixed(2)])}}><HBarChart data={standings} domain={[0, 1]} format={v => v.toFixed(2)} labelWidth={100} height={240} /></ChartCard>
      </div>
    </details>}
    </div></details>
    <div className="deployment-note"><span className="eyebrow">Deployment context</span><p>Tools run in a sandbox. Sessions, trust, and events are held in memory; the document index can persist on disk. <a href="#/architecture">See implementation details →</a></p></div>
  </div>;
}

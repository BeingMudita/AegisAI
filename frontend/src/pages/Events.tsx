import { useState } from "react";
import { Download } from "lucide-react";
import { downloadJson } from "../download";

import { api, qs } from "../api";
import { useAuth } from "../auth";
import { Badge, Button, Card, Empty, ErrorNote, PageHeader, inputClass, severityTone } from "../components/ui";
import { formatTime, useApi } from "../hooks";
import type { SecurityEvent } from "../types";

const TYPES = ["PROMPT_INJECTION", "POLICY_VIOLATION", "TRUST_DEGRADATION", "TOOL_DENIED", "AUTH_FAILURE", "ANOMALY"];
const SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];

export default function Events() {
  const { user } = useAuth();
  const [eventType, setEventType] = useState("");
  const [severity, setSeverity] = useState("");
  const [agent, setAgent] = useState("");
  const [live, setLive] = useState(true);
  const path = `/api/security-events${qs({ event_type: eventType, severity, agent, limit: 200 })}`;
  const events = useApi<{ events: SecurityEvent[]; count: number }>(path, live ? 3000 : undefined);
  const [error, setError] = useState<string | null>(null);

  async function clearAll() {
    if (!window.confirm("Clear every event from the in-memory audit buffer?")) return;
    try {
      await api.del("/api/security-events");
      void events.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Security events"
        description="The audit log: every blocked injection, policy violation, trust drop and denied tool call, newest first. Click a row to see its details."
        actions={<Button variant="ghost" size="sm" disabled={!events.data?.events.length || events.loading || Boolean(events.error)} onClick={() => downloadJson("aegis-security-events.json", { exported_at: new Date().toISOString(), filters: { event_type: eventType, severity, agent }, limit: 200, events: events.data?.events })}><Download className="h-4 w-4" /> Export filtered events</Button>}
      />
      <div className="flex flex-wrap items-center gap-2">
        <select
          className={`${inputClass} w-auto`}
          value={eventType}
          onChange={(e) => setEventType(e.target.value)}
          aria-label="Event type"
        >
          <option value="">All types</option>
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {t.replace(/_/g, " ").toLowerCase()}
            </option>
          ))}
        </select>
        <select
          className={`${inputClass} w-auto`}
          value={severity}
          onChange={(e) => setSeverity(e.target.value)}
          aria-label="Severity"
        >
          <option value="">All severities</option>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {s.toLowerCase()}
            </option>
          ))}
        </select>
        <input
          className={`${inputClass} w-40`}
          placeholder="Agent"
          value={agent}
          onChange={(e) => setAgent(e.target.value)}
          aria-label="Agent"
        />
        <label className="flex items-center gap-1.5 text-sm text-ink-2">
          <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /> Live
        </label>
        {user?.role === "ADMIN" && (
          <Button variant="ghost" className="ml-auto" onClick={() => void clearAll()}>
            Clear
          </Button>
        )}
      </div>
      <ErrorNote message={events.error ?? error} />
      <Card title={events.loading ? "Loading events…" : `${events.data?.count ?? 0} events`} subtitle="Newest first · showing up to 200 matching events; export includes this view">
        {events.data?.events.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-ink-2">
                  <th className="border-b border-edge py-1.5 pr-3 font-semibold">Time</th>
                  <th className="border-b border-edge py-1.5 pr-3 font-semibold">Severity</th>
                  <th className="border-b border-edge py-1.5 pr-3 font-semibold">Type</th>
                  <th className="border-b border-edge py-1.5 pr-3 font-semibold">Source</th>
                  <th className="border-b border-edge py-1.5 pr-3 font-semibold">Agent</th>
                  <th className="border-b border-edge py-1.5 font-semibold">Description</th>
                </tr>
              </thead>
              <tbody>
                {events.data.events.map((e) => (
                  <tr key={e.id} className="align-top">
                    <td className="tabular border-b border-edge py-1.5 pr-3 text-xs text-ink-2">
                      {formatTime(e.created_at)}
                    </td>
                    <td className="border-b border-edge py-1.5 pr-3">
                      <Badge tone={severityTone(e.severity)}>{e.severity.toLowerCase()}</Badge>
                    </td>
                    <td className="border-b border-edge py-1.5 pr-3 text-xs">
                      {e.event_type.replace(/_/g, " ").toLowerCase()}
                    </td>
                    <td className="border-b border-edge py-1.5 pr-3 text-xs text-ink-2">{e.source}</td>
                    <td className="border-b border-edge py-1.5 pr-3 text-xs">{e.agent ?? "—"}</td>
                    <td className="border-b border-edge py-1.5 text-xs">
                      <details>
                        <summary className="cursor-pointer">{e.description}</summary>
                        <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-all font-mono text-[11px] text-ink-2">
                          {JSON.stringify(e.details, null, 2)}
                        </pre>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>No events match.</Empty>
        )}
      </Card>
    </div>
  );
}

import { isStaff, useAuth } from "../auth";
import { Badge, Card, Chip, Empty, PageHeader, actionTone, riskTone } from "../components/ui";
import { formatTime, useApi } from "../hooks";
import type { AgentInfo, ToolCall, ToolInfo } from "../types";

export default function Policies() {
  const { user } = useAuth();
  const staff = isStaff(user);
  const agents = useApi<AgentInfo[]>("/api/agents");
  const tools = useApi<{ tools: ToolInfo[] }>(staff ? "/api/tools" : null);
  const requests = useApi<ToolCall[]>(staff ? "/api/tools/requests?limit=25" : null, 4000);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Policies & tools"
        description="What each agent is allowed to do. A tool call must pass both the agent's policy below and the global tool registry (risk level, kill switch, minimum trust, rate limit)."
      />
      <div className="grid items-stretch gap-6 md:grid-cols-2">
        {(agents.data ?? []).map((a) => (
          <Card key={a.name} title={a.name} subtitle="Per-agent policy — deny by default, block-list wins">
            <dl className="space-y-2 text-sm">
              <div>
                <dt className="mb-1 text-xs text-ink-2">Allowed tools</dt>
                <dd className="flex flex-wrap gap-1">
                  {a.allowed_tools.map((t) => (
                    <Chip key={t}>{t}</Chip>
                  ))}
                </dd>
              </div>
              <div>
                <dt className="mb-1 text-xs text-ink-2">Blocked tools</dt>
                <dd className="flex flex-wrap gap-1">
                  {a.blocked_tools.map((t) => (
                    <Chip key={t} struck>
                      {t}
                    </Chip>
                  ))}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-ink-2">Allowed domains (incl. subdomains)</dt>
                <dd>{a.allowed_domains.join(", ") || "none"}</dd>
              </div>
              <div>
                <dt className="text-xs text-ink-2">Sensitive data (PII redacted)</dt>
                <dd>{a.sensitive_data.join(", ") || "none"}</dd>
              </div>
            </dl>
          </Card>
        ))}
      </div>

      {staff && (
        <Card
          title="Tool registry"
          subtitle="Global rules from default_policies.yaml — a tool must pass these and the agent policy"
        >
          {tools.data ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-ink-2">
                    <th className="border-b border-edge py-1.5 pr-3 font-semibold">Tool</th>
                    <th className="border-b border-edge py-1.5 pr-3 font-semibold">Risk</th>
                    <th className="border-b border-edge py-1.5 pr-3 font-semibold">Status</th>
                    <th className="border-b border-edge py-1.5 pr-3 font-semibold">Min trust</th>
                    <th className="border-b border-edge py-1.5 pr-3 font-semibold">Rate / min</th>
                    <th className="border-b border-edge py-1.5 font-semibold">Description</th>
                  </tr>
                </thead>
                <tbody>
                  {tools.data.tools.map((t) => (
                    <tr key={t.name}>
                      <td className="border-b border-edge py-1.5 pr-3 font-mono text-xs">{t.name}</td>
                      <td className="border-b border-edge py-1.5 pr-3">
                        <Badge tone={riskTone(t.risk_level)}>{t.risk_level.toLowerCase()}</Badge>
                      </td>
                      <td className="border-b border-edge py-1.5 pr-3">
                        <Badge tone={t.enabled ? "good" : "critical"}>{t.enabled ? "enabled" : "disabled"}</Badge>
                      </td>
                      <td className="tabular border-b border-edge py-1.5 pr-3 text-xs">
                        {t.required_trust.toFixed(2)}
                      </td>
                      <td className="tabular border-b border-edge py-1.5 pr-3 text-xs">
                        {t.rate_limit_per_min ?? "—"}
                      </td>
                      <td className="border-b border-edge py-1.5 text-xs text-ink-2">
                        {t.description}
                        {t.domain_checked_argument && ` (domain-checked: ${t.domain_checked_argument})`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty>Loading…</Empty>
          )}
        </Card>
      )}

      {staff && (
        <Card title="Gateway log" subtitle="Latest tool requests and where they were stopped">
          {requests.data?.length ? (
            <ul className="divide-y divide-edge">
              {requests.data.map((r) => (
                <li key={r.id} className="flex flex-wrap items-start gap-x-3 gap-y-1 py-2 text-sm">
                  <span className="tabular w-20 shrink-0 text-xs text-muted">{formatTime(r.requested_at)}</span>
                  <Badge tone={actionTone(r.status)}>{r.status.toLowerCase()}</Badge>
                  <span className="font-mono text-xs">
                    {r.agent} → {r.tool}
                  </span>
                  <span className="min-w-0 flex-1 text-xs text-ink-2">{r.decision_reason}</span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No tool requests yet.</Empty>
          )}
        </Card>
      )}
    </div>
  );
}

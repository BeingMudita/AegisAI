import { Bot, CheckCircle2, Clock3, FileWarning, Hourglass, ShieldCheck, UserCheck, XCircle } from "lucide-react";
import { useState } from "react";

import { api } from "../api";
import { useAuth } from "../auth";
import DocumentReviews from "../components/DocumentReviews";
import { Badge, Button, Card, Empty, ErrorNote, PageHeader, StatTile, Tabs, actionTone, inputClass } from "../components/ui";
import { formatTime, useApi } from "../hooks";
import type { ApprovalQueue, ToolCall } from "../types";

function minutesLeft(iso?: string | null): string {
  if (!iso) return "";
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return "expiring";
  const m = Math.ceil(ms / 60000);
  return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min left` : `${m} min left`;
}

function decision(r: ToolCall): { label: string; tone: ReturnType<typeof actionTone> } {
  if (r.status === "EXECUTED") return { label: "approved · executed", tone: "good" };
  if (r.decision_reason.startsWith("No decision")) return { label: "expired", tone: "neutral" };
  if (r.decision_reason.startsWith("Rejected")) return { label: "rejected", tone: "critical" };
  if (r.decision_reason.startsWith("Approved, but")) return { label: "approved · re-check failed", tone: "serious" };
  return { label: r.status.toLowerCase(), tone: actionTone(r.status) };
}

function Arguments({ args }: { args: Record<string, unknown> }) {
  return (
    <dl className="grid gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[7rem_minmax(0,1fr)]">
      {Object.entries(args).map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-xs font-medium tracking-wide text-ink-2 uppercase">{k}</dt>
          <dd className="max-h-32 overflow-auto font-mono text-xs break-words whitespace-pre-wrap text-ink">
            {typeof v === "string" ? v : JSON.stringify(v)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function PendingCard({ request, canDecide, onDone }: { request: ToolCall; canDecide: boolean; onDone: () => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function decide(action: "approve" | "reject") {
    setBusy(action);
    setError(null);
    try {
      await api.post(`/api/approvals/${request.id}/${action}`, { note });
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  const passed = request.checks.filter((c) => c.passed);
  return (
    <Card
      title={
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-mono">{request.tool}</span>
          <span className="text-ink-2">requested by</span>
          <span>{request.agent}</span>
        </span>
      }
      subtitle={`Request ${request.id.slice(0, 8)} · ${formatTime(request.requested_at)}`}
      icon={Hourglass}
      actions={<Badge tone="warning">{minutesLeft(request.expires_at)}</Badge>}
    >
      <div className="space-y-4">
        <p className="text-sm text-ink-2">{request.decision_reason}</p>
        <div className="rounded-lg border border-edge bg-surface-2/50 p-3">
          <Arguments args={request.arguments} />
        </div>
        <div>
          <div className="eyebrow mb-1.5">Automatic checks already passed</div>
          <div className="flex flex-wrap gap-1.5">
            {passed.map((c) => (
              <Badge key={c.checkpoint} tone="good" title={c.detail}>
                {c.checkpoint.replace("_", " ")}
              </Badge>
            ))}
          </div>
        </div>
        {canDecide ? (
          <div className="space-y-2 border-t border-edge pt-4">
            <input
              className={inputClass}
              placeholder="Note for the audit trail (optional)"
              value={note}
              maxLength={500}
              onChange={(e) => setNote(e.target.value)}
              aria-label="Review note"
            />
            <ErrorNote message={error} />
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => void decide("approve")} disabled={busy !== null}>
                <CheckCircle2 className="h-4 w-4" /> {busy === "approve" ? "Re-checking…" : "Approve & run"}
              </Button>
              <Button variant="danger" onClick={() => void decide("reject")} disabled={busy !== null}>
                <XCircle className="h-4 w-4" /> Reject
              </Button>
            </div>
            <p className="text-xs text-muted">
              Approving re-runs every checkpoint first — if the agent&apos;s trust, policy or the domain list changed,
              the action is still refused.
            </p>
          </div>
        ) : (
          <p className="border-t border-edge pt-3 text-xs text-muted">Only administrators can decide.</p>
        )}
      </div>
    </Card>
  );
}

export default function Approvals() {
  const { user } = useAuth();
  const queue = useApi<ApprovalQueue>("/api/approvals", 3000);
  const waiting = useApi<{ pending: number; tools: number; documents: number }>("/api/approvals/pending-count", 10000);
  const pending = queue.data?.pending ?? [];
  const recent = queue.data?.recent ?? [];
  const count = (pred: (r: ToolCall) => boolean) => recent.filter(pred).length;
  // Open on whichever queue has something waiting (agent actions first).
  const [chosen, setChosen] = useState<"agent" | "documents" | null>(null);
  const tab = chosen ?? (pending.length || !waiting.data?.documents ? "agent" : "documents");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Approvals"
        description="Everything that waits for a person. Agent actions: high-impact requests that passed every automatic checkpoint (approving re-verifies them before the action runs; rejecting lowers the agent's trust). Documents: uploads where the ingestion firewall found something, to keep or remove."
      />
      <Tabs
        tabs={[
          { id: "agent" as const, label: "Agent actions", icon: Bot, count: pending.length },
          { id: "documents" as const, label: "Documents", icon: FileWarning, count: waiting.data?.documents },
        ]}
        value={tab}
        onChange={setChosen}
      />
      {tab === "documents" ? (
        <DocumentReviews admin={user?.role === "ADMIN"} onChanged={() => void waiting.reload()} />
      ) : (
      <div className="reveal space-y-6">
      <ErrorNote message={queue.error} />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile icon={Hourglass} tone="warning" label="Waiting" value={pending.length} note="need a decision" />
        <StatTile
          icon={CheckCircle2}
          tone="good"
          label="Approved"
          value={count((r) => r.status === "EXECUTED")}
          note="recent decisions"
        />
        <StatTile
          icon={XCircle}
          tone="critical"
          label="Rejected"
          value={count((r) => r.decision_reason.startsWith("Rejected"))}
          note="recent decisions"
        />
        <StatTile
          icon={Clock3}
          tone="neutral"
          label="Expiry"
          value={`${queue.data?.ttl_minutes ?? "–"} min`}
          note="before a request lapses"
        />
      </div>

      {pending.length ? (
        <div className="grid items-start gap-6 xl:grid-cols-2">
          {pending.map((r) => (
            <PendingCard key={r.id} request={r} canDecide={user?.role === "ADMIN"} onDone={() => void queue.reload()} />
          ))}
        </div>
      ) : (
        <Card>
          <Empty icon={ShieldCheck}>
            Nothing is waiting. Try asking FinanceAgent to “Email the overdue invoices to cfo@company.com” in the Agent
            workspace.
          </Empty>
        </Card>
      )}

      <Card
        title="Recent decisions"
        subtitle="Newest first — the full record is also in the tool gateway log"
        icon={UserCheck}
      >
        {recent.length ? (
          <div className="-mx-5 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-edge text-left text-xs text-ink-2">
                  <th className="px-5 py-2 font-semibold">Requested</th>
                  <th className="px-3 py-2 font-semibold">Action</th>
                  <th className="px-3 py-2 font-semibold">Decision</th>
                  <th className="px-3 py-2 font-semibold">Reviewer</th>
                  <th className="px-5 py-2 font-semibold">Reason</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((r) => {
                  const d = decision(r);
                  return (
                    <tr key={r.id} className="border-b border-edge align-top">
                      <td className="tabular px-5 py-2.5 text-xs text-ink-2">{formatTime(r.requested_at)}</td>
                      <td className="px-3 py-2.5">
                        <div className="font-mono text-xs">{r.tool}</div>
                        <div className="text-xs text-muted">{r.agent}</div>
                      </td>
                      <td className="px-3 py-2.5">
                        <Badge tone={d.tone}>{d.label}</Badge>
                      </td>
                      <td className="px-3 py-2.5 text-xs">
                        {r.reviewed_by ?? "—"}
                        {r.review_note && <div className="text-muted">“{r.review_note}”</div>}
                      </td>
                      <td className="px-5 py-2.5 text-xs text-ink-2">{r.decision_reason}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>No decisions yet.</Empty>
        )}
      </Card>
      </div>
      )}
    </div>
  );
}

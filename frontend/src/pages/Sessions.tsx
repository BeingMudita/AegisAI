import { useState } from "react";
import {
  ArrowRight,
  Ban,
  CheckCircle2,
  ChevronRight,
  Clock,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";

import { isStaff, useAuth } from "../auth";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorNote,
  PageHeader,
  formatTokens,
  toneVar,
  type Tone,
} from "../components/ui";
import { formatTime, useApi } from "../hooks";
import type { AgentTurn, SessionRecord, SessionSummary, ToolCall } from "../types";

type Decision = "ALLOW" | "CONFIRM" | "BLOCK";

/** ALLOW / CONFIRM / BLOCK for a turn — the firewall FLAG action maps to CONFIRM. */
export function decisionOf(turn: AgentTurn): Decision {
  const denied = turn.tool_calls.some((c) => c.status === "DENIED" || c.output_action === "BLOCK");
  if (turn.blocked || denied) return "BLOCK";
  const flagged =
    turn.trace.some((e) => e.status === "flagged") ||
    turn.tool_calls.some((c) => c.output_action === "FLAG");
  return flagged ? "CONFIRM" : "ALLOW";
}

const DECISION_TONE: Record<Decision, Tone> = { ALLOW: "good", CONFIRM: "warning", BLOCK: "critical" };

export function statusTone(status: string): Tone {
  if (status === "blocked" || status === "denied" || status === "failed") return "critical";
  if (status === "flagged" || status === "redacted") return "warning";
  if (status === "skipped") return "neutral";
  return "good";
}

const STAGE_LABEL: Record<string, string> = {
  input_firewall: "Input firewall",
  retrieval: "Guarded retrieval",
  plan: "Plan",
  tool: "Tool gateway",
  respond: "Compose",
  output_guard: "Output guard",
};

/** The kill-chain for one turn: each security checkpoint as a node, severed where a defence stopped it. */
function AttackGraph({ turn }: { turn: AgentTurn }) {
  const stages = turn.trace;
  if (!stages.length) return <Empty>No trace recorded for this turn.</Empty>;
  return (
    <ol className="flex flex-wrap items-stretch gap-0">
      {stages.map((stage, i) => {
        const tone = statusTone(stage.status);
        const c = toneVar(tone);
        const neutral = tone === "good" || tone === "neutral";
        const stopped = stage.status === "blocked" || stage.status === "denied";
        const next = stages[i + 1];
        return (
          <li key={`${stage.stage}-${i}`} className="flex items-stretch">
            <div
              className="flex min-w-[150px] max-w-[220px] flex-col gap-1 rounded-lg border border-edge p-2.5"
              style={{
                borderColor: neutral ? undefined : c,
                background: neutral ? "var(--surface-2)" : `color-mix(in srgb, ${c} 8%, var(--surface))`,
              }}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-semibold tracking-wide text-ink uppercase">
                  {STAGE_LABEL[stage.stage] ?? stage.stage}
                </span>
                <Badge tone={tone}>{stage.status}</Badge>
              </div>
              <p className="text-[11px] leading-snug text-ink-2">{stage.detail}</p>
            </div>
            {i < stages.length - 1 &&
              (stopped ? (
                <div className="flex w-8 shrink-0 items-center justify-center" title="Attack stopped here" aria-label="stopped">
                  <Ban className="h-4 w-4" style={{ color: "var(--critical)" }} />
                </div>
              ) : (
                <div className="flex w-8 shrink-0 items-center justify-center" aria-hidden>
                  <ChevronRight className="h-4 w-4" style={{ color: next ? "var(--muted)" : "transparent" }} />
                </div>
              ))}
          </li>
        );
      })}
    </ol>
  );
}

function ToolRow({ call }: { call: ToolCall }) {
  const failedAt = call.checks.find((c) => !c.passed);
  const tone: Tone =
    call.status === "EXECUTED" ? (call.output_action === "BLOCK" ? "warning" : "good") : "critical";
  return (
    <li className="py-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={tone}>{call.status.toLowerCase()}</Badge>
        <span className="font-mono text-xs">{call.tool}</span>
        {failedAt && (
          <span className="text-xs text-ink-2">
            stopped at <strong>{failedAt.checkpoint}</strong>
          </span>
        )}
        {call.output_action === "BLOCK" && <Badge tone="warning">output withheld</Badge>}
      </div>
      <p className="mt-0.5 text-xs text-ink-2">{call.decision_reason}</p>
    </li>
  );
}

function TurnCard({ turn, index }: { turn: AgentTurn; index: number }) {
  const decision = decisionOf(turn);
  return (
    <Card
      title={`Turn ${index + 1}`}
      subtitle={turn.message}
      actions={
        <span className="flex items-center gap-2">
          <Badge tone={DECISION_TONE[decision]}>{decision}</Badge>
          <span className="text-xs text-ink-2">
            {turn.duration_ms} ms{turn.usage && ` · ${formatTokens(turn.usage)}`}
          </span>
        </span>
      }
    >
      <div className="space-y-4">
        <div>
          <div className="mb-2 text-xs font-semibold tracking-wide text-ink-2 uppercase">
            Security checkpoints
          </div>
          <div className="overflow-x-auto pb-1">
            <AttackGraph turn={turn} />
          </div>
        </div>
        {turn.tool_calls.length > 0 && (
          <div>
            <div className="mb-1 text-xs font-semibold tracking-wide text-ink-2 uppercase">
              Tool calls
            </div>
            <ul className="divide-y divide-edge">
              {turn.tool_calls.map((c) => (
                <ToolRow key={c.id} call={c} />
              ))}
            </ul>
          </div>
        )}
        <details className="rounded-lg border border-edge bg-surface-2/50 p-3">
          <summary className="cursor-pointer text-xs font-semibold text-ink-2">Agent answer</summary>
          <p className="mt-2 text-sm whitespace-pre-wrap text-ink">{turn.answer || "—"}</p>
        </details>
      </div>
    </Card>
  );
}

export default function Sessions() {
  const { user } = useAuth();
  const staff = isStaff(user);
  const list = useApi<{ sessions: SessionSummary[] }>("/api/sessions", 5000);
  const [selected, setSelected] = useState<string | null>(null);
  const detail = useApi<SessionRecord>(selected ? `/api/sessions/${selected}` : null, 4000);

  const sessions = list.data?.sessions ?? [];
  const active = detail.data;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Sessions & attack reconstruction"
        description={
          staff
            ? "Replay any session's guarded turns. Each turn is reconstructed as its security kill-chain — follow where a request flowed and exactly which checkpoint stopped an attack."
            : "Replay your sessions and see how each request was handled at every security checkpoint."
        }
        actions={
          <Button variant="ghost" size="sm" onClick={() => { void list.reload(); void detail.reload(); }}>
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </Button>
        }
      />
      <ErrorNote message={list.error ?? detail.error} />
      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        <Card title="Sessions" subtitle={`${sessions.length} total · newest first`}>
          {sessions.length ? (
            <ul className="space-y-1">
              {sessions.map((s) => {
                const isActive = s.id === selected;
                return (
                  <li key={s.id}>
                    <button
                      onClick={() => setSelected(s.id)}
                      aria-current={isActive ? "true" : undefined}
                      className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition ${
                        isActive ? "bg-surface-2 font-semibold" : "hover:bg-surface-2"
                      }`}
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block truncate">{s.agent}</span>
                        <span className="block text-[11px] text-ink-2">
                          {s.turns} turn{s.turns === 1 ? "" : "s"}
                          {s.blocked_turns > 0 && ` · ${s.blocked_turns} blocked`}
                          {staff && ` · ${s.owner}`}
                        </span>
                      </span>
                      {s.blocked_turns > 0 ? (
                        <ShieldAlert className="h-4 w-4" style={{ color: "var(--critical)" }} />
                      ) : (
                        <ShieldCheck className="h-4 w-4" style={{ color: "var(--good)" }} />
                      )}
                      <ArrowRight className="h-3.5 w-3.5 text-muted" />
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : (
            <Empty icon={Clock}>
              {list.loading ? "Loading sessions…" : "No sessions yet. Run a request in the agent workspace."}
            </Empty>
          )}
        </Card>

        <div className="space-y-4">
          {!selected && (
            <Card title="Select a session">
              <Empty icon={ShieldCheck}>Pick a session on the left to reconstruct its security timeline.</Empty>
            </Card>
          )}
          {active && (
            <>
              <Card title={active.agent} subtitle={`Session ${active.id}`}>
                <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
                  <span>
                    <span className="text-ink-2">Owner:</span> {active.owner}
                  </span>
                  <span>
                    <span className="text-ink-2">Status:</span> {active.status.toLowerCase()}
                  </span>
                  <span>
                    <span className="text-ink-2">Opened:</span> {formatTime(active.created_at)}
                  </span>
                  <span>
                    <span className="text-ink-2">Turns:</span> {active.turns.length}
                  </span>
                  <span className="flex items-center gap-1.5">
                    <CheckCircle2 className="h-4 w-4" style={{ color: "var(--good)" }} />
                    {active.turns.filter((t) => decisionOf(t) === "ALLOW").length} allow ·{" "}
                    {active.turns.filter((t) => decisionOf(t) === "CONFIRM").length} confirm ·{" "}
                    {active.turns.filter((t) => decisionOf(t) === "BLOCK").length} block
                  </span>
                </div>
              </Card>
              {active.turns.length ? (
                active.turns.map((t, i) => <TurnCard key={t.id ?? i} turn={t} index={i} />)
              ) : (
                <Card title="No turns">
                  <Empty>This session has no turns yet.</Empty>
                </Card>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

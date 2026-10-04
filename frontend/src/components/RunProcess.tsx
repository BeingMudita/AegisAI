import { Check, Circle, Loader2, ShieldX } from "lucide-react";
import type { RunProgress, TraceEntry } from "../types";

const STAGES = [
  ["input_firewall", "Screen input", "Check identity, trust, and injection signals"],
  ["retrieval", "Find context", "Retrieve and screen relevant knowledge"],
  ["plan", "Plan action", "Decide whether a tool is needed"],
  ["tool", "Check tools", "Apply policy, trust, and output checks"],
  ["respond", "Compose answer", "Use the screened evidence"],
  ["output_guard", "Protect output", "Redact sensitive data before release"],
];

export default function RunProcess({ progress, busy, trace, failed = false }: { progress: RunProgress | null; busy: boolean; trace?: TraceEntry[]; failed?: boolean }) {
  const entries = busy || failed ? progress?.stages ?? [] : trace ?? progress?.stages ?? [];
  const state = busy ? progress?.status ?? "waiting" : failed ? "failed" : progress?.status ?? (trace?.some(e => e.status === "blocked") ? "blocked" : trace ? "completed" : "idle");
  return <section className="process-panel" aria-label="Agent processing stages">
    <div className="mb-5 flex items-start justify-between gap-3"><div><span className="eyebrow">Execution monitor</span><h2 className="mt-1 text-base font-semibold">Every step, accounted for.</h2></div><span className="process-state" role="status">{state === "waiting" ? "Awaiting server" : state === "idle" ? "Ready" : state}</span></div>
    <ol className="process-steps">{STAGES.map(([id, title, description], index) => {
      const entry = [...entries].reverse().find(e => e.stage === id);
      const running = busy && entry?.status === "running";
      const stopped = entry && ["blocked", "denied", "failed"].includes(entry.status);
      const label = running ? "Running" : entry ? entry.status : state === "completed" || state === "blocked" ? "Not needed" : state === "failed" ? "Not confirmed" : "Waiting";
      const Icon = running ? Loader2 : stopped ? ShieldX : entry ? Check : Circle;
      return <li key={id} className={`process-step ${running ? "running" : ""} ${stopped ? "stopped" : ""}`}>
        <span className="process-icon"><Icon className={`h-4 w-4 ${running ? "animate-spin" : ""}`} /></span>
        <div className="min-w-0 flex-1"><div className="flex flex-wrap justify-between gap-1"><strong className="text-xs font-semibold">{String(index + 1).padStart(2, "0")} · {title}</strong><span className="text-[11px] capitalize text-ink-2">{label}</span></div><p className="mt-1 text-xs leading-relaxed text-ink-2">{description}</p></div>
      </li>;
    })}</ol>
    <p className="mt-4 border-t border-edge pt-3 text-[11px] leading-relaxed text-ink-2">Server-reported stages. Planning and tool checks may repeat; a blocked input ends the run early.</p>
  </section>;
}

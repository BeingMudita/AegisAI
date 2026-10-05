import { ArrowRight, Bot, Database, FileCheck2, Fingerprint, Network, ScrollText, ShieldCheck, Workflow } from "lucide-react";
import { useState } from "react";
import { isStaff, useAuth } from "../auth";
import { Badge, Card, PageHeader } from "../components/ui";

const COMPONENTS = [
  { id: "identity", title: "Identity & sessions", label: "Authenticated requests", icon: Fingerprint, x: 2, y: 12, route: "console", file: "app/api/routes/sessions.py", description: "JWT authentication identifies the caller. Session ownership controls access to conversations and live progress. One turn can run per session at a time.", input: "User message + bearer token", output: "Authorized agent turn", boundary: "In memory by default; with STORAGE_BACKEND=postgres, sessions, turns, users and session locks are durable and shared by every API worker." },
  { id: "firewall", title: "Injection firewall", label: "Normalize · inspect · decide", icon: ShieldCheck, x: 27, y: 12, route: "firewall", file: "app/firewall/scanner.py", description: "Normalizes obfuscated text and applies weighted signatures. Input can pass, be flagged, or be blocked. Retrieved content and tool output are screened again at their own boundaries.", input: "Untrusted text from every channel", output: "Allow, flag, or block decision", boundary: "Signature detection is imperfect; policy and trust checks remain essential." },
  { id: "runtime", title: "Agent runtime", label: "Retrieve · plan · act", icon: Bot, x: 52, y: 12, route: "console", file: "app/agents/runtime.py", description: "A LangGraph workflow retrieves context, asks the brain to propose actions, and routes every tool call through the gateway. Planning and acting repeat up to the configured step limit.", input: "Screened message + trusted context", output: "Proposed tool calls and a draft answer", boundary: "Ollama when available; deterministic rule-based fallback. Model proposals never authorize tool execution." },
  { id: "output", title: "Output guard", label: "Redact · release", icon: FileCheck2, x: 77, y: 12, route: "console", file: "app/agents/runtime.py · guard_output", description: "Redacts secrets and policy-sensitive personal data, and removes detected exfiltration links before releasing the final answer. The console keeps the associated security trace for inspection.", input: "Draft answer", output: "Guarded answer + decision evidence", boundary: "Live progress publishes stage status only, never unfinished model output." },
  { id: "knowledge", title: "Guarded knowledge", label: "Screen · quarantine · index", icon: Database, x: 2, y: 62, route: "knowledge", file: "app/rag/knowledge_base.py", description: "Uploads, server files, and pasted text are chunked and screened. Poisoned chunks are quarantined. Retrieval filters source trust and screens candidate context again before the agent sees it.", input: "Documents and search queries", output: "Screened chunks with source provenance", boundary: "The local index can persist on disk. Embeddings use a semantic model when installed, otherwise hashing." },
  { id: "controls", title: "Policy & trust", label: "Deny by default", icon: ScrollText, x: 27, y: 62, route: "policies", file: "app/policies/engine.py · app/trust/engine.py", description: "Per-agent tool and domain allow-lists combine with global kill switches, minimum trust scores, and rate limits. Violations lower trust; clean behavior restores it gradually.", input: "Agent identity + requested capability", output: "Permission and trust decisions", boundary: "In memory by default; in Postgres mode policies come from the policies table and trust updates are row-locked so concurrent workers never lose one." },
  { id: "gateway", title: "Tool gateway", label: "Check · execute · rescan", icon: Workflow, x: 52, y: 62, route: "policies", file: "app/tools/gateway.py", description: "Checks registry, policy, domain, argument firewall, trust, and rate limit in order. High-impact tools then wait in the Approvals queue for an administrator, and every check is re-run at approval time. Allowed calls execute in the sandbox; their outputs pass injection screening and DLP before returning to the agent.", input: "Proposed tool + arguments", output: "Guarded result or denial reason", boundary: "Current tools simulate database, email, web, and shell operations. They do not perform real external actions." },
  { id: "audit", title: "Security telemetry", label: "Record · investigate", icon: Network, x: 77, y: 62, route: "events", file: "app/telemetry/store.py", description: "Security components record incidents and decision counters with agent and session context. Operators use the event log to inspect injection detections, policy violations, and trust degradation.", input: "Decisions across security boundaries", output: "Event log and overview metrics", boundary: "Bounded and in memory by default; in Postgres mode the audit log is durable and cannot be erased through the API. Red-team lab runs use an isolated log." },
];
const EDGES = [
  { from: "identity", to: "firewall", d: "M220 108 H270", label: "request" },
  { from: "firewall", to: "runtime", d: "M470 108 H520", label: "screened input" },
  { from: "runtime", to: "output", d: "M720 108 H770", label: "answer" },
  { from: "knowledge", to: "runtime", d: "M120 273 V208 H580 V163", label: "context" },
  { from: "controls", to: "gateway", d: "M470 328 H520", label: "authorization" },
  { from: "runtime", to: "gateway", d: "M650 163 V273", label: "tool call / result", both: true },
  { from: "gateway", to: "audit", d: "M720 328 H770", label: "decisions" },
  { from: "output", to: "audit", d: "M870 163 V273", label: "events" },
];

export default function Architecture() {
  const [selected, setSelected] = useState("runtime");
  const { user } = useAuth();
  const component = COMPONENTS.find(c => c.id === selected)!;
  return <div className="space-y-6">
    <PageHeader title="System architecture" description="Follow a request through the security boundaries. Select a component to inspect its role, data flow, and implementation." actions={<Badge tone="neutral">Current implementation</Badge>} />
    <div className="architecture-layout">
      <Card title="The path from input to action" subtitle="Arrows show primary data paths. Firewall checks and telemetry also run inside retrieval and tools." icon={Network}>
        <div className="architecture-scroll" role="region" aria-label="Interactive component map" tabIndex={0}>
          <div className="architecture-canvas">
            <svg className="architecture-edges" viewBox="0 0 1000 440" aria-hidden="true">
              <defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3" orient="auto-start-reverse"><path d="M0 0 L6 3 L0 6" fill="context-stroke" /></marker></defs>
              {EDGES.map(edge => <path key={edge.from + edge.to} d={edge.d} className={edge.from === selected || edge.to === selected ? "edge-selected" : ""} markerEnd="url(#arrow)" markerStart={edge.both ? "url(#arrow)" : undefined} />)}
            </svg>
            {COMPONENTS.map(c => <button key={c.id} className={`architecture-node ${selected === c.id ? "selected" : ""}`} style={{ left: `${c.x}%`, top: `${c.y}%` }} onClick={() => setSelected(c.id)} aria-pressed={selected === c.id} aria-controls="component-details">
              <c.icon className="h-5 w-5 text-accent" /><strong>{c.title}</strong><span>{c.label}</span>
            </button>)}
            <span className="map-caption" style={{ left: "2%", top: "0%" }}>01 / REQUEST PATH</span>
            <span className="map-caption" style={{ left: "2%", top: "51%" }}>02 / KNOWLEDGE & CONTROL PLANE</span>
          </div>
        </div>
        <p className="border-t border-edge pt-3 text-xs text-ink-2">Select with a click or Tab + Enter. Highlighted connections belong to the selected component.</p>
      </Card>
      <section id="component-details" className="component-details" aria-live="polite">
        <span className="eyebrow">Component detail</span>
        <component.icon className="my-5 h-8 w-8 text-accent" />
        <h2 className="text-xl font-semibold tracking-tight">{component.title}</h2>
        <p className="mt-3 text-sm leading-relaxed text-ink-2">{component.description}</p>
        <dl className="my-6 space-y-4 text-sm"><div><dt className="eyebrow">Receives</dt><dd className="mt-1">{component.input}</dd></div><div><dt className="eyebrow">Produces</dt><dd className="mt-1">{component.output}</dd></div></dl>
        <p className="rounded-lg border border-edge bg-surface-2 p-3 text-xs leading-relaxed text-ink-2">{component.boundary}</p>
        <code className="my-4 block break-words text-[11px] text-ink-2">{component.file}</code>
        {component.route !== "events" || isStaff(user) ? <a className="action-link" href={`#/${component.route}`}>Open {component.route === "knowledge" ? "knowledge base" : component.route === "console" ? "agent workspace" : component.route} <ArrowRight className="h-4 w-4" /></a> : <p className="text-xs text-muted">Event details are available to administrators and security analysts.</p>}
      </section>
    </div>
    <Card title="Connected data flows" subtitle="A text alternative to the diagram, including the tool execution loop.">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{EDGES.map(e => <div key={e.from + e.to} className="rounded-lg border border-edge p-3 text-xs"><div className="font-medium">{COMPONENTS.find(c => c.id === e.from)?.title} {e.both ? "↔" : "→"} {COMPONENTS.find(c => c.id === e.to)?.title}</div><div className="mt-1 text-ink-2">{e.label}</div></div>)}</div>
    </Card>
  </div>;
}

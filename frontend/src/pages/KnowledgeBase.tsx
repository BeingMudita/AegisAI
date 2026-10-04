import {
  Binary,
  Check,
  ClipboardPaste,
  Copy,
  Database,
  Eye,
  FileText,
  FolderInput,
  FolderOpen,
  Layers,
  Loader2,
  RefreshCw,
  Scissors,
  Search,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { Fragment, useEffect, useRef, useState, type DragEvent, type FormEvent } from "react";

import { api, upload } from "../api";
import { isStaff, useAuth } from "../auth";
import { PipelineFlow, type Stage } from "../components/pipeline";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorNote,
  Meter,
  PageHeader,
  Tabs,
  actionTone,
  formatBytes,
  formatNumber,
  inputClass,
  trustTone,
} from "../components/ui";
import { useApi } from "../hooks";
import type {
  DocumentChunkView,
  InboxListing,
  IngestJob,
  IngestReport,
  KbStats,
  QuarantinedChunk,
  RetrievalResult,
  TrustLevel,
} from "../types";

const LEVELS: { value: TrustLevel; hint: string }[] = [
  { value: "VERIFIED", hint: "official, reviewed content" },
  { value: "HIGH", hint: "internal team documents" },
  { value: "MEDIUM", hint: "general internal content" },
  { value: "LOW", hint: "partner / vendor content" },
  { value: "UNTRUSTED", hint: "public web — never shown to agents" },
];

const ACCEPT = ".pdf,.docx,.txt,.md,.markdown,.log,.csv,.tsv,.json,.jsonl,.ndjson,.html,.htm";
const STAGE_ORDER = ["PARSING", "SCREENING", "EMBEDDING", "INDEXING", "COMPLETED"] as const;
const STAGE_LABEL: Record<string, string> = {
  QUEUED: "Queued",
  PARSING: "Parsing",
  SCREENING: "Firewall",
  EMBEDDING: "Embedding",
  INDEXING: "Indexing",
  COMPLETED: "Done",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
};

type Tab = "add" | "documents" | "search" | "quarantine" | "sources";

function TrustSelect({ value, onChange }: { value: TrustLevel; onChange: (v: TrustLevel) => void }) {
  return (
    <select
      className={inputClass}
      value={value}
      onChange={(e) => onChange(e.target.value as TrustLevel)}
      aria-label="Source trust level"
    >
      {LEVELS.map((l) => (
        <option key={l.value} value={l.value}>
          {l.value.toLowerCase()} — {l.hint}
        </option>
      ))}
    </select>
  );
}

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

interface SourceSettings {
  perFile: boolean;
  source: string;
  trust: TrustLevel;
}

/** Where the files come from and how far to trust them. */
function SourceFields({ value, onChange }: { value: SourceSettings; onChange: (v: SourceSettings) => void }) {
  return (
    <div className="space-y-3">
      <label className="flex items-start gap-2.5 text-sm">
        <input
          type="checkbox"
          className="mt-0.5 h-4 w-4 accent-[var(--series-1)]"
          checked={value.perFile}
          onChange={(e) => onChange({ ...value, perFile: e.target.checked })}
        />
        <span>
          <span className="font-medium text-ink">Treat each file as its own source</span>
          <span className="block text-xs text-ink-2">
            Recommended. A source that contains an injection loses trust — this way one bad file can't hide the clean
            files uploaded with it.
          </span>
        </span>
      </label>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">
          <span className="mb-1 block text-xs font-medium text-ink-2">Source name</span>
          <input
            className={`${inputClass} disabled:opacity-50`}
            value={value.perFile ? "(file name)" : value.source}
            disabled={value.perFile}
            onChange={(e) => onChange({ ...value, source: e.target.value })}
          />
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-xs font-medium text-ink-2">How much do you trust it?</span>
          <TrustSelect value={value.trust} onChange={(trust) => onChange({ ...value, trust })} />
        </label>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ upload
function UploadPanel({ onQueued }: { onQueued: () => void }) {
  const [files, setFiles] = useState<File[]>([]);
  const [settings, setSettings] = useState<SourceSettings>({ perFile: true, source: "Uploads", trust: "MEDIUM" });
  const [drag, setDrag] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  function add(list: FileList | null) {
    if (list) setFiles((prev) => [...prev, ...Array.from(list)]);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDrag(false);
    add(e.dataTransfer.files);
  }

  async function send() {
    setError(null);
    setProgress(0);
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    form.append("source", settings.source || "Uploads");
    form.append("trust_level", settings.trust);
    form.append("source_per_file", String(settings.perFile));
    try {
      await upload<IngestJob[]>("/api/retrieval/uploads", form, setProgress);
      setFiles([]);
      onQueued();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setProgress(null);
    }
  }

  return (
    <Card
      title="Upload files"
      subtitle="Drag files here from your computer. Each file is processed in the background."
      icon={UploadCloud}
    >
      <div className="space-y-4">
        <button
          type="button"
          onClick={() => input.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={onDrop}
          className={`flex w-full flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-center transition ${
            drag ? "border-accent bg-accent/5" : "border-edge hover:border-accent/60 hover:bg-surface-2"
          }`}
        >
          <UploadCloud className="h-9 w-9 text-accent" strokeWidth={1.5} />
          <span className="text-sm font-medium text-ink">Drop files here or click to browse</span>
          <span className="text-xs text-muted">PDF, Word (.docx), TXT, MD, CSV, TSV, JSON, JSONL, HTML, LOG</span>
        </button>
        <input ref={input} type="file" multiple accept={ACCEPT} hidden onChange={(e) => add(e.target.files)} />

        {files.length > 0 && (
          <ul className="max-h-40 divide-y divide-edge overflow-auto rounded-lg border border-edge">
            {files.map((f, i) => (
              <li key={`${f.name}-${i}`} className="flex items-center gap-2 px-3 py-2 text-sm">
                <FileText className="h-4 w-4 shrink-0 text-muted" />
                <span className="min-w-0 flex-1 truncate">{f.name}</span>
                <span className="tabular text-xs text-muted">{formatBytes(f.size)}</span>
                <button
                  onClick={() => setFiles(files.filter((_, j) => j !== i))}
                  className="rounded p-0.5 text-muted hover:text-ink"
                  aria-label={`Remove ${f.name}`}
                >
                  <X className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        )}

        <SourceFields value={settings} onChange={setSettings} />

        {progress !== null && (
          <div>
            <div className="mb-1 flex justify-between text-xs text-ink-2">
              <span>Uploading…</span>
              <span className="tabular">{Math.round(progress * 100)}%</span>
            </div>
            <Meter value={progress} label="Upload progress" />
          </div>
        )}
        <ErrorNote message={error} />
        <Button onClick={() => void send()} disabled={!files.length || progress !== null} className="w-full">
          <UploadCloud className="h-4 w-4" />
          {files.length ? `Upload ${files.length} file${files.length > 1 ? "s" : ""}` : "Choose files to upload"}
        </Button>
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------- inbox
function InboxPanel({ onQueued }: { onQueued: () => void }) {
  const inbox = useApi<InboxListing>("/api/retrieval/inbox");
  const [settings, setSettings] = useState<SourceSettings>({ perFile: true, source: "Inbox", trust: "MEDIUM" });
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const supported = inbox.data?.files.filter((f) => f.supported) ?? [];

  async function importAll() {
    setError(null);
    try {
      await api.post<IngestJob[]>("/api/retrieval/inbox/import", {
        files: null,
        source: settings.source || "Inbox",
        trust_level: settings.trust,
        source_per_file: settings.perFile,
      });
      onQueued();
    } catch (e) {
      setError(errorText(e));
    }
  }

  function copyPath() {
    if (!inbox.data) return;
    void navigator.clipboard?.writeText(inbox.data.directory).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    });
  }

  return (
    <Card
      title="Server folder (for large datasets)"
      subtitle="Copy files straight into this folder on the server — no browser upload — then import them."
      icon={FolderInput}
      actions={
        <Button variant="ghost" size="sm" onClick={() => void inbox.reload()}>
          <RefreshCw className="h-3.5 w-3.5" /> Refresh
        </Button>
      }
    >
      <div className="space-y-4">
        <div className="flex items-center gap-2 rounded-lg border border-edge bg-surface-2 px-3 py-2">
          <FolderOpen className="h-4 w-4 shrink-0 text-muted" />
          <code className="min-w-0 flex-1 truncate text-xs text-ink" title={inbox.data?.directory}>
            {inbox.data?.directory ?? "…"}
          </code>
          <button onClick={copyPath} className="rounded p-1 text-muted hover:text-ink" aria-label="Copy folder path">
            {copied ? <Check className="h-4 w-4" style={{ color: "var(--good)" }} /> : <Copy className="h-4 w-4" />}
          </button>
        </div>

        {inbox.data && inbox.data.files.length > 0 ? (
          <ul className="max-h-40 divide-y divide-edge overflow-auto rounded-lg border border-edge">
            {inbox.data.files.map((f) => (
              <li key={f.path} className="flex items-center gap-2 px-3 py-2 text-sm">
                <FileText className="h-4 w-4 shrink-0 text-muted" />
                <span className="min-w-0 flex-1 truncate">{f.path}</span>
                <span className="tabular text-xs text-muted">{formatBytes(f.size_bytes)}</span>
                {!f.supported && <Badge tone="neutral">skipped</Badge>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="rounded-lg border border-dashed border-edge px-3 py-4 text-center text-xs text-muted">
            The folder is empty. Copy files into it (subfolders are fine), then press Refresh.
          </p>
        )}

        <SourceFields value={settings} onChange={setSettings} />
        <ErrorNote message={error} />
        <Button onClick={() => void importAll()} disabled={!supported.length} className="w-full">
          <FolderInput className="h-4 w-4" />
          {supported.length ? `Import ${supported.length} file${supported.length > 1 ? "s" : ""}` : "Nothing to import"}
        </Button>
      </div>
    </Card>
  );
}

function PastePanel({ onDone }: { onDone: () => void }) {
  const [doc, setDoc] = useState({ title: "", source: "", trust_level: "MEDIUM" as TrustLevel, content: "" });
  const [report, setReport] = useState<IngestReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function ingest(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      setReport(await api.post<IngestReport>("/api/retrieval/documents", doc));
      onDone();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Card
      title="Paste text"
      subtitle="Quick way to add a short document. Blank lines separate chunks."
      icon={ClipboardPaste}
    >
      <form onSubmit={ingest} className="grid gap-3 sm:grid-cols-3">
        <input
          className={inputClass}
          placeholder="Title"
          value={doc.title}
          onChange={(e) => setDoc({ ...doc, title: e.target.value })}
        />
        <input
          className={inputClass}
          placeholder="Source"
          value={doc.source}
          onChange={(e) => setDoc({ ...doc, source: e.target.value })}
        />
        <TrustSelect value={doc.trust_level} onChange={(v) => setDoc({ ...doc, trust_level: v })} />
        <textarea
          className={`${inputClass} min-h-28 sm:col-span-3`}
          placeholder="Paste the document text…"
          value={doc.content}
          onChange={(e) => setDoc({ ...doc, content: e.target.value })}
        />
        <div className="flex flex-wrap items-center gap-3 sm:col-span-3">
          <Button type="submit" disabled={!doc.title || !doc.source || !doc.content}>
            Add to knowledge base
          </Button>
          {report && (
            <span className="text-sm text-ink-2">
              {report.chunks_indexed}/{report.chunks_total} indexed · {report.chunks_flagged} sanitized ·{" "}
              {report.chunks_quarantined} quarantined
            </span>
          )}
        </div>
        <div className="sm:col-span-3">
          <ErrorNote message={error} />
        </div>
      </form>
    </Card>
  );
}

// -------------------------------------------------------------------- jobs
function JobRow({ job, canCancel, onCancel }: { job: IngestJob; canCancel: boolean; onCancel: () => void }) {
  const running = !["COMPLETED", "FAILED", "CANCELLED"].includes(job.stage);
  const fraction = job.size_bytes ? job.bytes_read / job.size_bytes : running ? 0 : 1;
  const stageIndex = STAGE_ORDER.indexOf(job.stage as (typeof STAGE_ORDER)[number]);
  const seconds =
    job.started_at && job.finished_at
      ? (new Date(job.finished_at).getTime() - new Date(job.started_at).getTime()) / 1000
      : null;

  return (
    <li className="space-y-2.5 py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-2">
        {running ? (
          <Loader2 className="h-4 w-4 animate-spin text-accent" />
        ) : (
          <FileText className="h-4 w-4 text-muted" />
        )}
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">{job.filename}</span>
        <span className="text-xs text-muted">
          {job.source} · {job.origin}
        </span>
        <Badge tone={trustTone(job.trust_level)}>{job.trust_level.toLowerCase()}</Badge>
        <Badge tone={actionTone(job.stage)}>{job.duplicate_of ? "Already indexed" : STAGE_LABEL[job.stage]}</Badge>
        {canCancel && running && (
          <Button variant="subtle" size="sm" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>

      <div className="flex items-center gap-1.5" aria-label="Pipeline stages">
        {STAGE_ORDER.map((s, i) => {
          const done = job.stage === "COMPLETED" || (stageIndex >= 0 && i < stageIndex);
          const current = s === job.stage && running;
          return (
            <div key={s} className="flex flex-1 flex-col gap-1">
              <div
                className={`h-1.5 rounded-full ${current ? "animate-pulse" : ""}`}
                style={{ background: done || current ? "var(--series-1)" : "var(--grid)" }}
              />
              <span className={`text-[10px] ${current ? "font-semibold text-ink" : "text-muted"}`}>
                {STAGE_LABEL[s]}
              </span>
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-2">
        <span className="tabular">
          {formatBytes(job.bytes_read)} / {formatBytes(job.size_bytes)} ({Math.round(Math.min(1, fraction) * 100)}%)
        </span>
        <span className="tabular">{formatNumber(job.chunks_indexed)} indexed</span>
        <span className="tabular">{formatNumber(job.chunks_flagged)} sanitized</span>
        <span className="tabular" style={job.chunks_quarantined ? { color: "var(--critical)" } : undefined}>
          {formatNumber(job.chunks_quarantined)} quarantined
        </span>
        {seconds !== null && <span className="tabular">{seconds.toFixed(1)} s</span>}
      </div>
      {job.duplicate_of && (
        <p className="text-xs text-muted">This content is already in the knowledge base, so it was not indexed again.</p>
      )}
      {job.error && <ErrorNote message={job.error} />}
    </li>
  );
}

// -------------------------------------------------------------------- page
export default function KnowledgeBase() {
  const { user } = useAuth();
  const admin = user?.role === "ADMIN";
  const staff = isStaff(user);
  const [tab, setTab] = useState<Tab>(admin ? "add" : "search");

  // Poll the job list fast only while something is ingesting; queuing files reloads it at once.
  const [ingesting, setIngesting] = useState(false);
  const jobs = useApi<IngestJob[]>(staff ? "/api/retrieval/jobs" : null, ingesting ? 1000 : 5000);
  const anyRunning = (jobs.data ?? []).some((j) => !["COMPLETED", "FAILED", "CANCELLED"].includes(j.stage));
  useEffect(() => setIngesting(anyRunning), [anyRunning]);
  const stats = useApi<KbStats>("/api/retrieval", anyRunning ? 1000 : 5000);
  const documents = useApi<IngestReport[]>(staff ? "/api/retrieval/documents" : null, anyRunning ? 2000 : 10000);
  const quarantine = useApi<QuarantinedChunk[]>(staff ? "/api/retrieval/quarantine" : null, anyRunning ? 2000 : 10000);

  const [query, setQuery] = useState("What are the invoice approval thresholds?");
  const [result, setResult] = useState<RetrievalResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openDoc, setOpenDoc] = useState<string | null>(null);
  const chunks = useApi<DocumentChunkView[]>(openDoc ? `/api/retrieval/documents/${openDoc}/chunks` : null);

  const s = stats.data;
  const runningJob = (jobs.data ?? []).find((j) => !["COMPLETED", "FAILED", "CANCELLED", "QUEUED"].includes(j.stage));
  const activeStage = runningJob?.stage;

  function refreshAll() {
    void jobs.reload();
    void stats.reload();
    void documents.reload();
    void quarantine.reload();
  }

  async function search(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      setResult(await api.post<RetrievalResult>("/api/retrieval/search", { query }));
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function removeDoc(doc: IngestReport) {
    if (!window.confirm(`Delete "${doc.title}" and its ${doc.chunks_indexed} chunks from the index?`)) return;
    try {
      await api.del(`/api/retrieval/documents/${doc.document_id}`);
      if (openDoc === doc.document_id) setOpenDoc(null);
      refreshAll();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function cancelJob(id: string) {
    await api.post(`/api/retrieval/jobs/${id}/cancel`).catch(() => undefined);
    void jobs.reload();
  }

  const stages: Stage[] = [
    {
      id: "files",
      label: "1 · Files in",
      icon: FileText,
      value: formatNumber(s?.documents ?? 0),
      detail: `documents · ${formatBytes(s?.bytes_ingested ?? 0)}`,
      active: activeStage === "PARSING",
    },
    {
      id: "chunk",
      label: "2 · Parse & chunk",
      icon: Scissors,
      value: formatNumber(s?.chunks_screened ?? 0),
      detail: "paragraph-sized chunks",
      active: activeStage === "PARSING",
    },
    {
      id: "screen",
      label: "3 · Firewall screen",
      icon: ShieldCheck,
      tone: s?.chunks_quarantined ? "warning" : "accent",
      value: `${formatNumber(s?.chunks_quarantined ?? 0)} blocked`,
      detail: `${formatNumber(s?.chunks_flagged ?? 0)} sanitized · injections never reach the index`,
      active: activeStage === "SCREENING",
    },
    {
      id: "embed",
      label: "4 · Embed",
      icon: Binary,
      value: <span className="font-mono text-base">{s?.embedder ?? "…"}</span>,
      detail: "text → vectors",
      active: activeStage === "EMBEDDING",
    },
    {
      id: "index",
      label: "5 · Vector index",
      icon: Database,
      value: formatNumber(s?.chunks_indexed ?? 0),
      detail: `chunks · ${formatBytes(s?.memory_bytes ?? 0)} in memory${s?.persisted ? " · saved to disk" : ""}`,
      active: activeStage === "INDEXING",
    },
    {
      id: "retrieve",
      label: "6 · Guarded retrieval",
      icon: Search,
      value: `${s?.sources.length ?? 0} sources`,
      detail: "trust-filtered and re-scanned before agents see it",
    },
  ];

  const tabs: { id: Tab; label: string; icon: typeof FileText; count?: number }[] = [
    ...(admin ? [{ id: "add" as const, label: "Add data", icon: UploadCloud }] : []),
    ...(staff ? [{ id: "documents" as const, label: "Documents", icon: Layers, count: documents.data?.length }] : []),
    { id: "search", label: "Test search", icon: Search },
    ...(staff
      ? [{ id: "quarantine" as const, label: "Quarantine", icon: ShieldAlert, count: quarantine.data?.length }]
      : []),
    ...(staff ? [{ id: "sources" as const, label: "Sources", icon: Database, count: s?.source_summaries.length }] : []),
  ];

  return (
    <div>
      <PageHeader
        title="Knowledge base"
        description="Add documents to the agents' knowledge base and watch them move through the pipeline. Every chunk is scanned by the prompt-injection firewall before it can be indexed — poisoned paragraphs are quarantined, suspicious ones sanitized."
      />

      <Card
        title="Ingestion pipeline"
        subtitle={
          runningJob
            ? `Processing ${runningJob.filename} — ${STAGE_LABEL[runningJob.stage].toLowerCase()}…`
            : "Live totals for everything in the knowledge base"
        }
        icon={Layers}
        className="mb-6"
      >
        <PipelineFlow stages={stages} />
      </Card>

      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      <div className="pt-6">
        <ErrorNote message={error} />

        {tab === "add" && admin && (
          <div className="space-y-6">
            <div className="grid items-stretch gap-6 lg:grid-cols-2">
              <UploadPanel onQueued={refreshAll} />
              <InboxPanel onQueued={refreshAll} />
            </div>
            <Card
              title="Processing queue"
              subtitle="One file at a time, streamed — progress updates live"
              icon={Loader2}
              actions={anyRunning ? <Badge tone="accent">running</Badge> : undefined}
            >
              {jobs.data?.length ? (
                <ul className="divide-y divide-edge">
                  {jobs.data.slice(0, 20).map((j) => (
                    <JobRow key={j.id} job={j} canCancel={admin} onCancel={() => void cancelJob(j.id)} />
                  ))}
                </ul>
              ) : (
                <Empty icon={UploadCloud}>No files processed yet — upload or import some above.</Empty>
              )}
            </Card>
            <PastePanel onDone={refreshAll} />
          </div>
        )}

        {tab === "documents" && staff && (
          <Card
            title="Documents in the knowledge base"
            subtitle="Newest first. Expand a row to see its chunks as they were indexed."
          >
            {documents.data?.length ? (
              <div className="-mx-5 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-edge text-left text-xs text-ink-2">
                      <th className="px-5 py-2 font-semibold">Document</th>
                      <th className="px-3 py-2 font-semibold">Source</th>
                      <th className="px-3 py-2 font-semibold">Trust</th>
                      <th className="px-3 py-2 text-right font-semibold">Size</th>
                      <th className="px-3 py-2 text-right font-semibold">Indexed</th>
                      <th className="px-3 py-2 text-right font-semibold">Sanitized</th>
                      <th className="px-3 py-2 text-right font-semibold">Quarantined</th>
                      <th className="px-5 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {documents.data.map((d) => (
                      <Fragment key={d.document_id}>
                        <tr className="border-b border-edge hover:bg-surface-2/60">
                          <td className="px-5 py-2.5">
                            <div className="font-medium text-ink">{d.title}</div>
                            <div className="text-xs text-muted">{new Date(d.created_at).toLocaleString()}</div>
                          </td>
                          <td className="px-3 py-2.5 text-ink-2">{d.source}</td>
                          <td className="px-3 py-2.5">
                            <Badge tone={trustTone(d.trust_level)}>{d.trust_level.toLowerCase()}</Badge>
                          </td>
                          <td className="tabular px-3 py-2.5 text-right text-ink-2">{formatBytes(d.size_bytes)}</td>
                          <td className="tabular px-3 py-2.5 text-right">{formatNumber(d.chunks_indexed)}</td>
                          <td className="tabular px-3 py-2.5 text-right">{formatNumber(d.chunks_flagged)}</td>
                          <td
                            className="tabular px-3 py-2.5 text-right"
                            style={d.chunks_quarantined ? { color: "var(--critical)" } : undefined}
                          >
                            {formatNumber(d.chunks_quarantined)}
                          </td>
                          <td className="px-5 py-2.5">
                            <div className="flex justify-end gap-1">
                              <Button
                                variant="subtle"
                                size="sm"
                                onClick={() => setOpenDoc(openDoc === d.document_id ? null : d.document_id)}
                                aria-expanded={openDoc === d.document_id}
                              >
                                <Eye className="h-3.5 w-3.5" /> Chunks
                              </Button>
                              {admin && (
                                <Button
                                  variant="subtle"
                                  size="sm"
                                  onClick={() => void removeDoc(d)}
                                  aria-label={`Delete ${d.title}`}
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </Button>
                              )}
                            </div>
                          </td>
                        </tr>
                        {openDoc === d.document_id && (
                          <tr className="border-b border-edge bg-surface-2/50">
                            <td colSpan={8} className="px-5 py-3">
                              {chunks.data?.length ? (
                                <ol className="max-h-80 space-y-2 overflow-auto">
                                  {chunks.data.map((c) => (
                                    <li key={c.chunk_index} className="rounded-lg border border-edge bg-surface p-3">
                                      <div className="mb-1 flex items-center gap-2 text-xs text-muted">
                                        <span className="tabular">#{c.chunk_index}</span>
                                        <Badge tone={actionTone(c.firewall_action)}>
                                          {c.firewall_action === "FLAG" ? "sanitized" : "clean"}
                                        </Badge>
                                      </div>
                                      <p className="text-xs whitespace-pre-line text-ink-2">{c.content}</p>
                                    </li>
                                  ))}
                                </ol>
                              ) : (
                                <p className="text-xs text-muted">No indexed chunks (all quarantined?).</p>
                              )}
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty icon={Layers}>No documents yet.</Empty>
            )}
          </Card>
        )}

        {tab === "search" && (
          <Card
            title="Test search"
            subtitle="See exactly what an agent would get back — and what was filtered out and why."
            icon={Search}
          >
            <form onSubmit={search} className="flex gap-2">
              <input className={inputClass} value={query} onChange={(e) => setQuery(e.target.value)} maxLength={2000} />
              <Button type="submit" disabled={!query.trim()}>
                <Search className="h-4 w-4" /> Search
              </Button>
            </form>
            {result && (
              <div className="mt-4 space-y-3">
                {result.chunks.length === 0 && result.dropped.length === 0 && <Empty>No relevant chunks.</Empty>}
                {result.chunks.map((c) => (
                  <div key={c.chunk_id} className="rounded-xl border border-edge p-4">
                    <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                      <Badge tone={c.sanitized ? "warning" : "good"}>{c.sanitized ? "sanitized" : "returned"}</Badge>
                      <span className="font-medium text-ink">{c.document_title}</span>
                      <span className="text-muted">
                        {c.source} · trust {c.source_trust.toFixed(2)} · similarity {c.similarity.toFixed(2)}
                      </span>
                    </div>
                    <p className="text-sm whitespace-pre-line text-ink-2">{c.content}</p>
                  </div>
                ))}
                {result.dropped.length > 0 && (
                  <div className="rounded-xl border border-edge bg-surface-2/60 p-4">
                    <div className="mb-2 text-xs font-semibold text-ink-2">Filtered out before reaching the agent</div>
                    <ul className="space-y-1.5">
                      {result.dropped.map((d, i) => (
                        <li key={`${d.chunk_id}-${i}`} className="flex flex-wrap items-center gap-2 text-xs">
                          <Badge tone="critical">dropped</Badge>
                          <span className="text-ink">{d.document_title}</span>
                          <span className="text-muted">{d.reason}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </Card>
        )}

        {tab === "quarantine" && staff && (
          <Card
            title="Quarantine"
            subtitle="Chunks the firewall refused to index. They are kept here for review and never shown to agents."
            icon={ShieldAlert}
          >
            {quarantine.data?.length ? (
              <ul className="space-y-3">
                {quarantine.data.map((q) => (
                  <li key={q.chunk_id} className="rounded-xl border border-edge p-4">
                    <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                      <Badge tone="critical">score {q.score.toFixed(2)}</Badge>
                      <span className="font-medium text-ink">{q.document_title}</span>
                      <span className="text-muted">{q.source}</span>
                    </div>
                    <div className="mb-2 flex flex-wrap gap-1">
                      {q.categories.map((c) => (
                        <span key={c} className="rounded-md bg-surface-2 px-1.5 py-0.5 text-[11px] text-ink-2">
                          {c.replace(/_/g, " ").toLowerCase()}
                        </span>
                      ))}
                    </div>
                    <p className="font-mono text-xs break-all text-ink-2">{q.excerpt}</p>
                  </li>
                ))}
              </ul>
            ) : (
              <Empty icon={ShieldCheck}>Nothing quarantined.</Empty>
            )}
          </Card>
        )}

        {tab === "sources" && staff && (
          <Card
            title="Sources"
            subtitle="A source that serves injected content loses trust; below 0.30 its chunks are no longer retrieved."
            icon={Database}
          >
            <div className="-mx-5 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-edge text-left text-xs text-ink-2">
                    <th className="px-5 py-2 font-semibold">Source</th>
                    <th className="px-3 py-2 font-semibold">Declared</th>
                    <th className="w-1/3 px-3 py-2 font-semibold">Current trust</th>
                    <th className="px-3 py-2 text-right font-semibold">Documents</th>
                    <th className="px-5 py-2 text-right font-semibold">Chunks</th>
                  </tr>
                </thead>
                <tbody>
                  {(s?.source_summaries ?? []).map((src) => (
                    <tr key={src.source} className="border-b border-edge">
                      <td className="px-5 py-2.5 font-medium">{src.source}</td>
                      <td className="px-3 py-2.5">
                        <Badge tone={trustTone(src.trust_level)}>{src.trust_level.toLowerCase()}</Badge>
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-2">
                          <span className="tabular w-9 text-xs">{src.trust_score.toFixed(2)}</span>
                          <Meter
                            value={src.trust_score}
                            markers={[{ at: 0.3, label: "retrieval cut-off 0.30" }]}
                            label={`${src.source} trust`}
                          />
                        </div>
                      </td>
                      <td className="tabular px-3 py-2.5 text-right">{src.documents}</td>
                      <td className="tabular px-5 py-2.5 text-right">{formatNumber(src.chunks_indexed)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}

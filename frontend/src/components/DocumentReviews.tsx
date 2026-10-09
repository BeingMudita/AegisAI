import { CheckCircle2, ChevronLeft, ChevronRight, Eraser, FileWarning, Search, ShieldAlert, ShieldQuestion, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type ComponentType } from "react";

import { api, qs } from "../api";
import { useApi } from "../hooks";
import type { ArchiveChunk, DeleteDocumentsResult, DocumentReview, DocumentReviewPage, ReviewKind } from "../types";
import { Badge, Button, Card, Empty, ErrorNote, formatNumber, inputClass, type Tone } from "./ui";

const PAGE_SIZE = 25;
const BATCH = 1000; // the API's per-request limit for approve / delete

type Filter = ReviewKind | "all" | "approved";

const KIND: Record<ReviewKind, { label: string; tone: Tone; icon: ComponentType<{ className?: string }>; hint: string }> = {
  blocked: { label: "Blocked content", tone: "critical", icon: ShieldAlert, hint: "The firewall kept some chunks out of the index." },
  untrusted: { label: "Untrusted source", tone: "serious", icon: ShieldQuestion, hint: "Agents don't see this document until its source is trusted." },
  sanitized: { label: "Sanitized", tone: "warning", icon: Eraser, hint: "Suspicious text was removed before indexing." },
};

const STATUS_TONE: Record<ArchiveChunk["status"], Tone> = { ready: "good", sanitized: "warning", low: "serious", blocked: "critical" };
const STATUS_LABEL: Record<ArchiveChunk["status"], string> = { ready: "ready", sanitized: "sanitized", low: "low trust", blocked: "blocked" };

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));
const plural = (n: number, word: string) => `${formatNumber(n)} ${word}${n === 1 ? "" : "s"}`;

function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setSettled(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return settled;
}

function Findings({ documentId }: { documentId: string }) {
  const res = useApi<ArchiveChunk[]>(`/api/approvals/documents/${encodeURIComponent(documentId)}/findings`);
  if (res.error) return <ErrorNote message={res.error} />;
  if (!res.data) return <p className="text-xs text-muted" role="status">Loading what the firewall found…</p>;
  return (
    <ol className="max-h-96 space-y-2 overflow-auto pr-1">
      {res.data.map((c) => (
        <li key={c.chunk_index} className="rounded-lg border border-edge bg-surface p-3">
          <div className="mb-1.5 flex flex-wrap items-center gap-2 text-xs text-muted">
            <span className="tabular font-medium text-ink-2">Chunk {c.chunk_index + 1}</span>
            <Badge tone={STATUS_TONE[c.status]} title={c.reason}>{STATUS_LABEL[c.status]}</Badge>
            {c.firewall_score > 0 && <span className="tabular">firewall score {c.firewall_score.toFixed(2)}</span>}
            {c.categories.length > 0 && <span>{c.categories.join(", ").replaceAll("_", " ").toLowerCase()}</span>}
            {c.excerpt_only && <span>excerpt</span>}
          </div>
          <p className="max-h-32 overflow-auto text-xs leading-relaxed whitespace-pre-line text-ink-2 [overflow-wrap:anywhere]">{c.content}</p>
        </li>
      ))}
    </ol>
  );
}

function ReviewRow({
  item,
  admin,
  checked,
  onCheck,
  onApprove,
  onRemove,
}: {
  item: DocumentReview;
  admin: boolean;
  checked: boolean;
  onCheck: () => void;
  onApprove: () => Promise<void>;
  onRemove: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const kind = KIND[item.review_kind];
  const I = kind.icon;
  const pending = item.review_status === "pending";

  async function run(action: () => Promise<void>) {
    setBusy(true);
    try { await action(); } finally { setBusy(false); setConfirming(false); }
  }

  return (
    <li className={`border-b border-edge px-5 py-3.5 ${checked ? "bg-surface-2" : ""}`}>
      <div className="flex items-start gap-3">
        {admin && (
          <input
            type="checkbox"
            className="mt-1 h-4 w-4 shrink-0"
            style={{ accentColor: "var(--brand)" }}
            checked={checked}
            onChange={onCheck}
            aria-label={`Select ${item.title}`}
          />
        )}
        <span className="mt-0.5 shrink-0" style={{ color: `var(--${kind.tone})` }} aria-hidden>
          <I className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <button className="min-w-0 truncate text-left text-sm font-medium text-ink hover:underline" onClick={() => setOpen(!open)} aria-expanded={open} title={item.filename ?? item.title}>
              {item.title}
            </button>
            <Badge tone={kind.tone}>{kind.label}</Badge>
            {!pending && <Badge tone="good">approved</Badge>}
          </div>
          <div className="mt-0.5 truncate text-xs text-muted">
            {item.section} / {item.folder} · {item.source} · added {new Date(item.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}
          </div>
          <p className="mt-1.5 text-xs leading-relaxed text-ink-2">{item.review_reason}</p>
          {!pending && (
            <p className="mt-1 text-xs text-muted">
              Approved by {item.reviewed_by} {item.reviewed_at && `· ${new Date(item.reviewed_at).toLocaleString()}`}
              {item.review_note && ` · “${item.review_note}”`}
            </p>
          )}
          {open && <div className="reveal mt-3"><Findings documentId={item.document_id} /></div>}
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
          <Button variant="subtle" size="sm" onClick={() => setOpen(!open)} aria-expanded={open}>
            {open ? "Hide" : "Findings"}
          </Button>
          {admin && (confirming ? (
            <>
              <Button variant="ghost" size="sm" onClick={() => setConfirming(false)} disabled={busy}>Cancel</Button>
              <Button variant="danger" size="sm" onClick={() => void run(onRemove)} disabled={busy}>
                <Trash2 className="h-3.5 w-3.5" /> {busy ? "Removing…" : "Remove"}
              </Button>
            </>
          ) : (
            <>
              {pending && (
                <Button size="sm" onClick={() => void run(onApprove)} disabled={busy}>
                  <CheckCircle2 className="h-3.5 w-3.5" /> Approve
                </Button>
              )}
              <Button variant="ghost" size="sm" onClick={() => setConfirming(true)} disabled={busy} aria-label={`Remove ${item.title}`}>
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </>
          ))}
        </div>
      </div>
    </li>
  );
}

/** Documents whose screening found something, for an administrator to approve or remove. */
export default function DocumentReviews({ admin, onChanged }: { admin: boolean; onChanged: () => void }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const search = useDebounced(query.trim(), 300);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<{ action: "approve" | "remove"; ids: string[]; label: string } | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const top = useRef<HTMLDivElement>(null);

  useEffect(() => { setOffset(0); setSelected(new Set()); }, [filter, search]);

  const params = (o: number, limit: number) => qs({
    kind: filter === "all" || filter === "approved" ? undefined : filter,
    status: filter === "approved" ? "approved" : "pending",
    q: search,
    offset: o,
    limit,
  });
  const page = useApi<DocumentReviewPage>(`/api/approvals/documents${params(offset, PAGE_SIZE)}`, 15000);
  const items = page.data?.items ?? [];
  const counts = page.data?.counts;
  const total = page.data?.total ?? 0;
  const pendingTotal = counts ? counts.blocked + counts.untrusted + counts.sanitized : 0;
  const pageIds = items.map((i) => i.document_id);
  const allOnPage = pageIds.length > 0 && pageIds.every((id) => selected.has(id));

  async function approve(ids: string[]) {
    for (let i = 0; i < ids.length; i += BATCH) {
      await api.post("/api/approvals/documents/approve", { document_ids: ids.slice(i, i + BATCH), note: note.trim() || null });
    }
  }
  async function remove(ids: string[]) {
    for (let i = 0; i < ids.length; i += BATCH) {
      await api.post<DeleteDocumentsResult>("/api/retrieval/documents/delete", { document_ids: ids.slice(i, i + BATCH) });
    }
  }
  async function allMatchingIds(): Promise<string[]> {
    const ids: string[] = [];
    for (let o = 0; ; o += 100) {
      const p = await api.get<DocumentReviewPage>(`/api/approvals/documents${params(o, 100)}`);
      ids.push(...p.items.map((i) => i.document_id));
      if (!p.has_more) return ids;
    }
  }

  function done(text: string) {
    setMessage({ ok: true, text });
    setSelected(new Set());
    setConfirm(null);
    void page.reload();
    onChanged();
  }

  async function runConfirmed() {
    if (!confirm) return;
    setBusy(confirm.action);
    setMessage(null);
    try {
      if (confirm.action === "approve") {
        await approve(confirm.ids);
        done(`Approved ${plural(confirm.ids.length, "document")}. They stay in the knowledge base as screened.`);
      } else {
        await remove(confirm.ids);
        done(`Removed ${plural(confirm.ids.length, "document")} from the knowledge base.`);
      }
    } catch (e) {
      setMessage({ ok: false, text: errorText(e) });
      void page.reload();
    } finally {
      setBusy(null);
    }
  }

  async function askAllMatching(action: "approve" | "remove") {
    setBusy("collect");
    setMessage(null);
    try {
      const ids = await allMatchingIds();
      setConfirm({ action, ids, label: `all ${plural(ids.length, "document")} in this view` });
      top.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (e) {
      setMessage({ ok: false, text: errorText(e) });
    } finally {
      setBusy(null);
    }
  }

  const filters: { id: Filter; label: string; count?: number; tone?: Tone }[] = [
    { id: "all", label: "Needs review", count: pendingTotal },
    { id: "blocked", label: "Blocked content", count: counts?.blocked, tone: "critical" },
    { id: "untrusted", label: "Untrusted source", count: counts?.untrusted, tone: "serious" },
    { id: "sanitized", label: "Sanitized", count: counts?.sanitized, tone: "warning" },
    { id: "approved", label: "Approved", count: counts?.approved, tone: "good" },
  ];

  return (
    <div className="reveal space-y-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {(["blocked", "untrusted", "sanitized"] as const).map((k) => {
          const K = KIND[k];
          const I = K.icon;
          return (
            <button
              key={k}
              onClick={() => setFilter(k)}
              aria-pressed={filter === k}
              className={`flex min-w-0 items-start gap-3 rounded-xl border bg-surface p-4 text-left shadow-card transition hover:bg-surface-2 ${filter === k ? "border-ink-2" : "border-edge"}`}
            >
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg" style={{ background: `color-mix(in srgb, var(--${K.tone}) 16%, transparent)`, color: `var(--${K.tone})` }}>
                <I className="h-5 w-5" />
              </span>
              <span className="min-w-0">
                <span className="block text-xs font-medium text-ink-2">{K.label}</span>
                <span className="tabular block text-2xl font-semibold tracking-tight text-ink">{counts ? formatNumber(counts[k]) : "…"}</span>
                <span className="block text-xs leading-relaxed text-muted">{K.hint}</span>
              </span>
            </button>
          );
        })}
        <button
          onClick={() => setFilter("approved")}
          aria-pressed={filter === "approved"}
          className={`flex min-w-0 items-start gap-3 rounded-xl border bg-surface p-4 text-left shadow-card transition hover:bg-surface-2 ${filter === "approved" ? "border-ink-2" : "border-edge"}`}
        >
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg" style={{ background: "color-mix(in srgb, var(--good) 16%, transparent)", color: "var(--good)" }}>
            <CheckCircle2 className="h-5 w-5" />
          </span>
          <span className="min-w-0">
            <span className="block text-xs font-medium text-ink-2">Approved</span>
            <span className="tabular block text-2xl font-semibold tracking-tight text-ink">{counts ? formatNumber(counts.approved) : "…"}</span>
            <span className="block text-xs leading-relaxed text-muted">Reviewed and kept.</span>
          </span>
        </button>
      </div>

      <Card
        title="Documents to review"
        icon={FileWarning}
        subtitle="Uploads where the ingestion firewall found something. The firewall already protects agents — blocked chunks never reach them and sanitized text is cleaned. Approve to keep a document as screened, or remove it."
        bodyClassName="-mx-5 -mb-5"
      >
        <div ref={top} className="space-y-3 border-b border-edge px-5 pb-4">
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Show">
            {filters.map((f) => (
              <button
                key={f.id}
                onClick={() => setFilter(f.id)}
                aria-pressed={filter === f.id}
                className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition ${filter === f.id ? "border-ink-2 bg-surface-2 text-ink" : "border-edge text-ink-2 hover:text-ink"}`}
              >
                {f.tone && <span className="h-2 w-2 rounded-full" style={{ background: `var(--${f.tone})` }} aria-hidden />}
                {f.label}
                {f.count !== undefined && <span className="tabular text-muted">{formatNumber(f.count)}</span>}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <label className="relative min-w-[200px] flex-1">
              <span className="sr-only">Search documents</span>
              <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted" />
              <input className={`${inputClass} pl-9`} placeholder="Search by name, source or folder…" value={query} onChange={(e) => setQuery(e.target.value)} />
            </label>
            {admin && filter !== "approved" && total > 0 && (
              <>
                <div className="w-full sm:w-60">
                  <input
                    className={inputClass}
                    placeholder="Approval note (optional)"
                    value={note}
                    maxLength={500}
                    onChange={(e) => setNote(e.target.value)}
                    aria-label="Approval note"
                  />
                </div>
                <Button variant="ghost" onClick={() => void askAllMatching("approve")} disabled={busy !== null}>
                  <CheckCircle2 className="h-4 w-4" /> {busy === "collect" ? "Collecting…" : `Approve all ${formatNumber(total)}`}
                </Button>
              </>
            )}
          </div>

          {admin && selected.size > 0 && (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-edge bg-surface-2 px-3 py-2 text-sm" role="group" aria-label="Selection">
              <span className="tabular text-ink-2">{formatNumber(selected.size)} selected</span>
              <span className="flex-1" />
              <Button variant="subtle" size="sm" onClick={() => setSelected(new Set())}>Clear</Button>
              {filter !== "approved" && (
                <Button size="sm" onClick={() => setConfirm({ action: "approve", ids: [...selected], label: plural(selected.size, "selected document") })}>
                  <CheckCircle2 className="h-3.5 w-3.5" /> Approve selected
                </Button>
              )}
              <Button variant="danger" size="sm" onClick={() => setConfirm({ action: "remove", ids: [...selected], label: plural(selected.size, "selected document") })}>
                <Trash2 className="h-3.5 w-3.5" /> Remove selected
              </Button>
            </div>
          )}

          {confirm && (
            <div role="alertdialog" aria-label="Confirm" className="reveal flex flex-wrap items-center gap-3 rounded-lg border border-edge bg-surface-2 px-3 py-2.5 text-sm">
              <span className="text-ink">
                {confirm.action === "approve"
                  ? `Approve ${confirm.label}? They stay in the knowledge base exactly as screened.`
                  : `Remove ${confirm.label}? They are deleted from the knowledge base and the index. This can't be undone.`}
              </span>
              <span className="flex-1" />
              <Button variant="ghost" size="sm" onClick={() => setConfirm(null)} disabled={busy !== null}>Cancel</Button>
              <Button variant={confirm.action === "approve" ? "primary" : "danger"} size="sm" onClick={() => void runConfirmed()} disabled={busy !== null}>
                {busy === confirm.action ? "Working…" : confirm.action === "approve" ? "Approve" : "Remove"}
              </Button>
            </div>
          )}

          {message && (
            <p role={message.ok ? "status" : "alert"} className="reveal rounded-lg border border-edge bg-surface-2 px-3 py-2 text-sm text-ink">
              <span aria-hidden className="mr-1.5 font-bold" style={{ color: message.ok ? "var(--good)" : "var(--critical)" }}>{message.ok ? "✓" : "✕"}</span>
              {message.text}
            </p>
          )}
          <ErrorNote message={page.error} />
        </div>

        {!page.data && page.loading ? (
          <p className="px-5 py-8 text-sm text-ink-2" role="status">Loading the review queue…</p>
        ) : items.length === 0 ? (
          <Empty icon={CheckCircle2}>
            {search ? `Nothing matches “${search}”.` : filter === "approved" ? "Nothing approved yet." : "Nothing to review. Every document passed screening cleanly."}
          </Empty>
        ) : (
          <>
            {admin && (
              <label className="flex items-center gap-3 border-b border-edge bg-surface-2/60 px-5 py-2 text-xs text-ink-2">
                <input
                  type="checkbox"
                  className="h-4 w-4"
                  style={{ accentColor: "var(--brand)" }}
                  checked={allOnPage}
                  onChange={() => setSelected((prev) => {
                    const next = new Set(prev);
                    for (const id of pageIds) {
                      if (allOnPage) next.delete(id);
                      else next.add(id);
                    }
                    return next;
                  })}
                />
                Select all on this page
              </label>
            )}
            <ul>
              {items.map((item) => (
                <ReviewRow
                  key={item.document_id}
                  item={item}
                  admin={admin}
                  checked={selected.has(item.document_id)}
                  onCheck={() => setSelected((prev) => {
                    const next = new Set(prev);
                    if (next.has(item.document_id)) next.delete(item.document_id);
                    else next.add(item.document_id);
                    return next;
                  })}
                  onApprove={async () => {
                    try { await approve([item.document_id]); done(`Approved “${item.title}”.`); }
                    catch (e) { setMessage({ ok: false, text: errorText(e) }); }
                  }}
                  onRemove={async () => {
                    try { await remove([item.document_id]); done(`Removed “${item.title}” from the knowledge base.`); }
                    catch (e) { setMessage({ ok: false, text: errorText(e) }); }
                  }}
                />
              ))}
            </ul>
            <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 text-xs text-muted">
              <span className="tabular">Showing {formatNumber(offset + 1)}–{formatNumber(Math.min(offset + PAGE_SIZE, total))} of {plural(total, "document")}</span>
              <div className="flex items-center gap-2">
                <Button variant="ghost" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} aria-label="Previous page">
                  <ChevronLeft className="h-3.5 w-3.5" />
                </Button>
                <span className="tabular">{formatNumber(Math.floor(offset / PAGE_SIZE) + 1)} / {formatNumber(Math.max(1, Math.ceil(total / PAGE_SIZE)))}</span>
                <Button variant="ghost" size="sm" disabled={!page.data?.has_more} onClick={() => setOffset(offset + PAGE_SIZE)} aria-label="Next page">
                  <ChevronRight className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}

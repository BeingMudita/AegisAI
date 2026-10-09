import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Boxes,
  ChevronLeft,
  ChevronRight,
  Database as DatabaseIcon,
  FileText,
  Folder,
  FolderOpen,
  FolderTree,
  HardDrive,
  Hash,
  Layers,
  Network,
  Plus,
  RefreshCw,
  Search,
  ShieldAlert,
  Trash2,
  X,
} from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { api } from "../api";
import { useAuth } from "../auth";
import { statusLabels } from "../components/archive/model";
import DataMap from "../components/archive/DataMap";
import VectorPanel from "../components/archive/VectorPanel";
import {
  buildTree,
  countFolders,
  docNodeKey,
  findNode,
  matchesQuery,
  pathTo,
  sortDocuments,
  type SortDir,
  type SortKey,
  type TreeNode,
} from "../components/archive/tree";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorNote,
  PageHeader,
  StatTile,
  Tabs,
  formatBytes,
  formatNumber,
  inputClass,
  trustTone,
  type Tone,
} from "../components/ui";
import { useApi } from "../hooks";
import type { ArchiveChunkPage, ArchiveDocument, ArchiveStatus, DeleteDocumentsResult } from "../types";

const PAGE_SIZE = 50;
const CHUNKS_PER_PAGE = 12;
const DELETE_BATCH = 1000; // the API's per-request limit

const statusTone: Record<ArchiveStatus, Tone> = { ready: "good", sanitized: "warning", blocked: "critical", low: "serious" };

// Columns appear from ``minWidth`` (px, Tailwind's sm/lg/xl/2xl) up. They're filtered in
// JS rather than hidden with CSS so the expanded row's colSpan always matches.
const COLUMNS: { key: SortKey; label: string; numeric?: boolean; width?: string; minWidth?: number }[] = [
  { key: "title", label: "Name" },
  { key: "location", label: "Location", width: "w-[240px]", minWidth: 1536 },
  { key: "trust", label: "Trust", width: "w-[124px]", minWidth: 1024 },
  { key: "chunks", label: "Chunks", numeric: true, width: "w-[84px]" },
  { key: "quarantined", label: "Quarantined", numeric: true, width: "w-[116px]", minWidth: 640 },
  { key: "size", label: "Size", numeric: true, width: "w-[88px]", minWidth: 640 },
  { key: "created", label: "Added", width: "w-[116px]", minWidth: 1280 },
];

function useViewportWidth(): number {
  const [width, setWidth] = useState(() => window.innerWidth);
  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return width;
}

const SORT_LABELS: Record<SortKey, string> = {
  title: "Name", location: "Location", source: "Source", trust: "Trust score", chunks: "Chunks",
  quarantined: "Quarantined", size: "Size", created: "Date added",
};
const TEXT_KEYS: SortKey[] = ["title", "location", "source"];

interface PendingDelete {
  label: string; // what is being deleted, for the dialog title
  documents: ArchiveDocument[];
}

const plural = (n: number, word: string) => `${formatNumber(n)} ${word}${n === 1 ? "" : "s"}`;

function locationLabel(doc: ArchiveDocument): string {
  return `${doc.section} / ${doc.folder}`;
}

// ------------------------------------------------------------------ tree
function TreeItem({
  node,
  depth,
  scopeKey,
  expanded,
  onToggle,
  onSelect,
}: {
  node: TreeNode;
  depth: number;
  scopeKey: string;
  expanded: Set<string>;
  onToggle: (key: string) => void;
  onSelect: (key: string) => void;
}) {
  const open = node.kind === "root" || expanded.has(node.key);
  const active = node.key === scopeKey;
  const I = node.kind === "root" ? DatabaseIcon : node.kind === "section" ? Layers : open && node.children.length ? FolderOpen : Folder;
  return (
    <li>
      <div
        className={`flex items-center rounded-lg pr-2 transition ${active ? "bg-surface-2 text-ink" : "text-ink-2 hover:bg-surface-2/60 hover:text-ink"}`}
        style={{ paddingLeft: depth * 14 + 2 }}
      >
        {node.children.length > 0 && node.kind !== "root" ? (
          <button
            onClick={() => onToggle(node.key)}
            aria-expanded={open}
            aria-label={`${open ? "Collapse" : "Expand"} ${node.name}`}
            className="rounded p-1 text-muted hover:text-ink"
          >
            <ChevronRight className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-90" : ""}`} />
          </button>
        ) : (
          <span className="w-[22px] shrink-0" aria-hidden />
        )}
        <button
          onClick={() => onSelect(node.key)}
          aria-current={active ? "true" : undefined}
          className={`flex min-w-0 flex-1 items-center gap-2 py-1.5 text-left text-sm ${active ? "font-semibold" : ""}`}
        >
          <I className="h-4 w-4 shrink-0" />
          <span className="truncate" title={node.name}>{node.name}</span>
          <span className="tabular ml-auto pl-2 text-xs text-muted">{formatNumber(node.documents.length)}</span>
        </button>
      </div>
      {open && node.children.length > 0 && (
        <ul>
          {node.children.map((c) => (
            <TreeItem key={c.key} node={c} depth={node.kind === "root" ? depth : depth + 1} scopeKey={scopeKey} expanded={expanded} onToggle={onToggle} onSelect={onSelect} />
          ))}
        </ul>
      )}
    </li>
  );
}

// ---------------------------------------------------------------- chunks
function ChunkPreview({ doc, onOpenVector }: { doc: ArchiveDocument; onOpenVector: (chunkId: string) => void }) {
  const [offset, setOffset] = useState(0);
  const res = useApi<ArchiveChunkPage>(
    `/api/retrieval/documents/${encodeURIComponent(doc.document_id)}/archive-chunks?offset=${offset}&limit=${CHUNKS_PER_PAGE}`,
  );
  const page = res.data?.document_id === doc.document_id && res.data.offset === offset ? res.data : null;
  return (
    <div className="space-y-3">
      <dl className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2 xl:grid-cols-4">
        <div><dt className="inline text-muted">File </dt><dd className="inline break-all text-ink-2">{doc.filename ?? "Pasted text"}</dd></div>
        <div><dt className="inline text-muted">Source </dt><dd className="inline break-all text-ink-2">{doc.source}</dd></div>
        <div><dt className="inline text-muted">Source trust </dt><dd className="tabular inline text-ink-2">{doc.source_trust.toFixed(2)} ({doc.trust_level.toLowerCase()})</dd></div>
        <div><dt className="inline text-muted">Retrieval </dt><dd className="inline text-ink-2">{doc.retrieval_reason ?? "Passes the trust gate"}</dd></div>
      </dl>
      <ErrorNote message={res.error} />
      {!page ? (
        !res.error && <p className="text-xs text-muted" role="status">Loading chunks…</p>
      ) : page.chunks.length === 0 ? (
        <p className="text-xs text-muted">This document has no stored chunks.</p>
      ) : (
        <>
          <ol className="max-h-96 space-y-2 overflow-auto pr-1">
            {page.chunks.map((c) => (
              <li key={c.chunk_index} className="rounded-lg border border-edge bg-surface p-3">
                <div className="mb-1.5 flex flex-wrap items-center gap-2 text-xs text-muted">
                  <span className="tabular font-medium text-ink-2">Chunk {c.chunk_index + 1}</span>
                  <Badge tone={statusTone[c.status]} title={c.reason}>{statusLabels[c.status]}</Badge>
                  {c.characters !== null && <span className="tabular">{formatNumber(c.characters)} chars</span>}
                  {c.estimated_tokens !== null && <span className="tabular">~{formatNumber(c.estimated_tokens)} tokens</span>}
                  {c.excerpt_only && <span>excerpt only</span>}
                  {c.indexed && (
                    <button
                      className="ml-auto inline-flex items-center gap-1 rounded text-ink-2 hover:text-ink hover:underline"
                      onClick={() => onOpenVector(`${doc.document_id}:${c.chunk_index}`)}
                    >
                      <Hash className="h-3 w-3" /> Open vector
                    </button>
                  )}
                </div>
                <p className="text-xs leading-relaxed whitespace-pre-line text-ink-2 [overflow-wrap:anywhere]">{c.content}</p>
              </li>
            ))}
          </ol>
          <div className="flex items-center justify-between gap-3 text-xs text-muted">
            <span className="tabular">
              Chunks {formatNumber(offset + 1)}–{formatNumber(Math.min(offset + CHUNKS_PER_PAGE, page.total))} of {formatNumber(page.total)}
            </span>
            <div className="flex gap-1">
              <Button variant="ghost" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - CHUNKS_PER_PAGE))} aria-label="Previous chunks">
                <ChevronLeft className="h-3.5 w-3.5" />
              </Button>
              <Button variant="ghost" size="sm" disabled={!page.has_more} onClick={() => setOffset(offset + CHUNKS_PER_PAGE)} aria-label="Next chunks">
                <ChevronRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- dialog
function ConfirmDelete({
  pending,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  pending: PendingDelete;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const latest = useRef({ busy, onCancel });
  latest.current = { busy, onCancel };
  const docs = pending.documents;
  const chunks = docs.reduce((n, d) => n + d.chunks_total, 0);
  const bytes = docs.reduce((n, d) => n + d.size_bytes, 0);

  // Mount only: the page re-renders on every poll and must not pull focus back to Cancel.
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    panel.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !latest.current.busy) latest.current.onCancel();
      if (event.key !== "Tab") return;
      const items = Array.from(panel.current?.querySelectorAll<HTMLElement>("button:not(:disabled)") ?? []);
      const first = items[0], last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("keydown", key); before?.focus(); };
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={() => !busy && onCancel()} />
      <div
        ref={panel}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="delete-title"
        aria-describedby="delete-summary"
        className="relative w-full max-w-md rounded-xl border border-edge bg-surface p-5 shadow-xl"
      >
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-surface-2 text-ink">
            <Trash2 className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <h2 id="delete-title" className="text-base font-semibold text-ink">Delete {pending.label}?</h2>
            <p id="delete-summary" className="mt-1 text-sm leading-relaxed text-ink-2">
              {plural(docs.length, "document")} · {plural(chunks, "chunk")} · {formatBytes(bytes)} will be removed from the
              knowledge base and the search index. Agents will no longer retrieve them. This can't be undone.
            </p>
          </div>
        </div>
        <ul className="mt-4 max-h-40 space-y-1 overflow-auto rounded-lg border border-edge bg-surface-2 p-3 text-xs text-ink-2">
          {docs.slice(0, 8).map((d) => (
            <li key={d.document_id} className="flex justify-between gap-3">
              <span className="truncate">{d.title}</span>
              <span className="shrink-0 text-muted">{locationLabel(d)}</span>
            </li>
          ))}
          {docs.length > 8 && <li className="text-muted">and {plural(docs.length - 8, "more document")}</li>}
        </ul>
        {error && <div className="mt-3"><ErrorNote message={error} /></div>}
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel} disabled={busy}>Cancel</Button>
          <Button variant="danger" onClick={onConfirm} disabled={busy}>
            <Trash2 className="h-4 w-4" />
            {busy ? "Deleting…" : `Delete ${plural(docs.length, "document")}`}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ page
function SortHeader({
  column,
  sort,
  onSort,
}: {
  column: (typeof COLUMNS)[number];
  sort: { key: SortKey; dir: SortDir };
  onSort: (key: SortKey) => void;
}) {
  const active = sort.key === column.key;
  const I = !active ? ArrowUpDown : sort.dir === "asc" ? ArrowUp : ArrowDown;
  return (
    <th
      scope="col"
      aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
      className={`px-3 py-2 font-semibold ${column.numeric ? "text-right" : "text-left"} ${column.width ?? ""}`}
    >
      <button
        onClick={() => onSort(column.key)}
        className={`inline-flex items-center gap-1 rounded hover:text-ink ${active ? "text-ink" : ""} ${column.numeric ? "flex-row-reverse" : ""}`}
      >
        {column.label}
        <I className={`h-3 w-3 ${active ? "" : "opacity-40"}`} />
      </button>
    </th>
  );
}

export default function Database() {
  const { user } = useAuth();
  const admin = user?.role === "ADMIN";
  const archive = useApi<ArchiveDocument[]>("/api/retrieval/archive", 30000);
  // Deleted ids stay hidden even if a poll that started before the delete lands afterwards.
  const [gone, setGone] = useState<Set<string>>(new Set());
  const documents = useMemo(() => (archive.data ?? []).filter((d) => !gone.has(d.document_id)), [archive.data, gone]);
  const tree = useMemo(() => buildTree(documents), [documents]);

  const [scopeKey, setScopeKey] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: "created", dir: "desc" });
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [openDoc, setOpenDoc] = useState<string | null>(null);
  const [tab, setTab] = useState<"documents" | "vectors" | "map">("documents");
  const [vectorId, setVectorId] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingDelete | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const selectAll = useRef<HTMLInputElement>(null);
  const viewport = useViewportWidth();
  const columns = COLUMNS.filter((c) => !c.minWidth || viewport >= c.minWidth);
  const showLocation = columns.some((c) => c.key === "location");

  const scope = findNode(tree, scopeKey) ?? tree;
  const trail = pathTo(tree, scope.key);
  const rows = useMemo(
    () => sortDocuments(scope.documents.filter((d) => matchesQuery(d, query)), sort.key, sort.dir),
    [scope, query, sort],
  );
  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const current = Math.min(page, pageCount - 1);
  const visible = rows.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE);
  const selectedDocs = documents.filter((d) => selected.has(d.document_id));
  const selectedInView = rows.filter((d) => selected.has(d.document_id)).length;

  useEffect(() => {
    if (!selectAll.current) return;
    selectAll.current.indeterminate = selectedInView > 0 && selectedInView < rows.length;
  }, [selectedInView, rows.length]);

  const totals = useMemo(() => {
    let chunks = 0, indexed = 0, quarantined = 0, bytes = 0;
    for (const d of documents) { chunks += d.chunks_total; indexed += d.chunks_indexed; quarantined += d.chunks_quarantined; bytes += d.size_bytes; }
    return { chunks, indexed, quarantined, bytes };
  }, [documents]);
  const scopeChunks = scope.documents.reduce((n, d) => n + d.chunks_total, 0);
  const scopeBytes = scope.documents.reduce((n, d) => n + d.size_bytes, 0);

  function selectScope(key: string) {
    setScopeKey(key);
    setPage(0);
    setOpenDoc(null);
    // Open the chosen node and everything above it, so it stays visible in the tree.
    setExpanded((prev) => new Set([...prev, ...pathTo(tree, key).map((n) => n.key)]));
  }

  function toggleNode(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function onSort(key: SortKey) {
    setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: TEXT_KEYS.includes(key) ? "asc" : "desc" }));
    setPage(0);
  }

  function toggleRow(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected((prev) => {
      const next = new Set(prev);
      const all = rows.length > 0 && rows.every((d) => next.has(d.document_id));
      for (const d of rows) {
        if (all) next.delete(d.document_id);
        else next.add(d.document_id);
      }
      return next;
    });
  }

  function askDelete(label: string, docs: ArchiveDocument[]) {
    if (!docs.length) return;
    setDeleteError(null);
    setNotice(null);
    setPending({ label, documents: docs });
  }

  async function confirmDelete() {
    if (!pending) return;
    setBusy(true);
    setDeleteError(null);
    const ids = pending.documents.map((d) => d.document_id);
    const removed: string[] = [];
    let missing = 0;
    try {
      for (let i = 0; i < ids.length; i += DELETE_BATCH) {
        const result = await api.post<DeleteDocumentsResult>("/api/retrieval/documents/delete", {
          document_ids: ids.slice(i, i + DELETE_BATCH),
        });
        removed.push(...result.deleted, ...result.missing);
        missing += result.missing.length;
      }
      const deleted = removed.length - missing;
      setNotice(
        `Deleted ${plural(deleted, "document")} from ${pending.label}.` +
          (missing ? ` ${plural(missing, "document")} had already been removed.` : ""),
      );
      setPending(null);
    } catch (err) {
      setDeleteError(
        (err instanceof Error ? err.message : "The documents could not be deleted.") +
          (removed.length ? ` ${plural(removed.length, "document")} were deleted before the error.` : ""),
      );
    } finally {
      if (removed.length) {
        setGone((prev) => new Set([...prev, ...removed]));
        setSelected((prev) => new Set([...prev].filter((id) => !removed.includes(id))));
        if (openDoc && removed.includes(openDoc)) setOpenDoc(null);
      }
      setBusy(false);
      void archive.reload();
    }
  }

  const scopeName = scope.kind === "root" ? "the whole database" : trail.slice(1).map((n) => n.name).join(" / ");
  const scopeTitle = (
    <span className="flex flex-wrap items-center gap-1">
      {trail.map((n, i) => (
        <Fragment key={n.key}>
          {i > 0 && <span className="text-muted">/</span>}
          {i < trail.length - 1 ? (
            <button className="text-ink-2 hover:text-ink hover:underline" onClick={() => selectScope(n.key)}>{n.name}</button>
          ) : (
            <span aria-current="location">{n.name}</span>
          )}
        </Fragment>
      ))}
    </span>
  );

  function openVector(chunkId: string) {
    setVectorId(chunkId);
    setTab("vectors");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  let body: ReactNode;
  if (!archive.data && archive.loading) {
    body = <p className="py-12 text-center text-sm text-ink-2" role="status">Loading the database…</p>;
  } else if (!archive.data) {
    body = (
      <div className="space-y-3">
        <ErrorNote message={archive.error ?? "The database could not load."} />
        <Button variant="ghost" onClick={() => void archive.reload()}>Try again</Button>
      </div>
    );
  } else {
    body = (
      <>
        <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          <StatTile label="Sections" value={formatNumber(tree.children.length)} icon={Layers} />
          <StatTile label="Folders" value={formatNumber(countFolders(tree))} icon={FolderTree} />
          <StatTile label="Documents" value={formatNumber(documents.length)} icon={FileText} />
          <StatTile label="Chunks" value={formatNumber(totals.chunks)} icon={Boxes} />
          <StatTile label="Quarantined" value={formatNumber(totals.quarantined)} icon={ShieldAlert} tone={totals.quarantined ? "critical" : "accent"} />
          <StatTile label="Stored files" value={formatBytes(totals.bytes)} icon={HardDrive} />
        </div>

        <div className="mb-6">
          <Tabs
            tabs={[
              { id: "documents" as const, label: "Documents", icon: FileText, count: documents.length },
              { id: "vectors" as const, label: "Vectors", icon: Hash, count: totals.indexed },
              { id: "map" as const, label: "Map", icon: Network },
            ]}
            value={tab}
            onChange={setTab}
          />
        </div>

        <div className="grid items-start gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
          <Card title="Structure" subtitle="Sections and folders. Pick one to list what's inside." icon={FolderTree} className="lg:sticky lg:top-20" bodyClassName="max-h-[60vh] overflow-auto lg:max-h-[calc(100vh-14rem)]">
            {documents.length ? (
              <ul aria-label="Database structure">
                <TreeItem node={tree} depth={0} scopeKey={scope.key} expanded={expanded} onToggle={toggleNode} onSelect={selectScope} />
              </ul>
            ) : (
              <p className="text-sm text-muted">No sections yet.</p>
            )}
          </Card>

          {tab === "map" ? (
            <Card
              className="reveal"
              title={scopeTitle}
              subtitle="Every section, folder and document as a graph. Bigger circles hold more data; document colours show what screening found. Click a folder to focus it, or a document to open its chunks."
            >
              <DataMap
                tree={tree}
                scopeKey={scope.key}
                onScope={selectScope}
                onOpenDocument={(d) => {
                  setTab("documents");
                  selectScope(docNodeKey(d));
                  setQuery(d.title);
                  setPage(0);
                  setOpenDoc(d.document_id);
                }}
              />
            </Card>
          ) : tab === "vectors" ? (
            <VectorPanel
              scope={scope}
              scopeTitle={scopeTitle}
              admin={admin}
              selectedId={vectorId}
              onSelect={setVectorId}
              onChanged={() => void archive.reload()}
            />
          ) : (
          <Card
            className="reveal"
            title={scopeTitle}
            subtitle={`${plural(scope.documents.length, "document")} · ${plural(scopeChunks, "chunk")} · ${formatBytes(scopeBytes)}${admin ? "" : " · Only administrators can delete documents."}`}
            actions={
              admin && scope.kind !== "root" && scope.documents.length > 0 ? (
                <Button variant="ghost" size="sm" onClick={() => askDelete(`${scope.kind} “${scopeName}”`, scope.documents)}>
                  <Trash2 className="h-3.5 w-3.5" /> Delete this {scope.kind}
                </Button>
              ) : undefined
            }
            bodyClassName="-mx-5 -mb-5"
          >
            <div className="flex flex-wrap items-center gap-3 border-b border-edge px-5 pb-4">
              <label className="relative min-w-[200px] flex-1">
                <span className="sr-only">Search documents</span>
                <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted" />
                <input
                  className={`${inputClass} pl-9`}
                  placeholder="Search by name, file, source or folder…"
                  value={query}
                  onChange={(e) => { setQuery(e.target.value); setPage(0); }}
                />
              </label>
              <div className="flex items-center gap-1">
                <label className="sr-only" htmlFor="db-sort">Sort by</label>
                <select
                  id="db-sort"
                  className={`${inputClass} w-auto py-2 pr-8`}
                  value={sort.key}
                  onChange={(e) => {
                    const key = e.target.value as SortKey;
                    setSort({ key, dir: TEXT_KEYS.includes(key) ? "asc" : "desc" });
                    setPage(0);
                  }}
                >
                  {(Object.keys(SORT_LABELS) as SortKey[]).map((k) => <option key={k} value={k}>Sort: {SORT_LABELS[k]}</option>)}
                </select>
                <Button
                  variant="ghost"
                  onClick={() => setSort((s) => ({ ...s, dir: s.dir === "asc" ? "desc" : "asc" }))}
                  aria-label={sort.dir === "asc" ? "Ascending; switch to descending" : "Descending; switch to ascending"}
                  title={sort.dir === "asc" ? "Ascending" : "Descending"}
                >
                  {sort.dir === "asc" ? <ArrowUp className="h-4 w-4" /> : <ArrowDown className="h-4 w-4" />}
                </Button>
              </div>
              {admin && selectedDocs.length > 0 && (
                <div className="flex items-center gap-2" role="group" aria-label="Selection">
                  <span className="tabular text-sm text-ink-2">{formatNumber(selectedDocs.length)} selected</span>
                  <Button variant="subtle" size="sm" onClick={() => setSelected(new Set())}>
                    <X className="h-3.5 w-3.5" /> Clear
                  </Button>
                  <Button variant="danger" size="sm" onClick={() => askDelete(selectedDocs.length === 1 ? `“${selectedDocs[0].title}”` : "the selected documents", selectedDocs)}>
                    <Trash2 className="h-3.5 w-3.5" /> Delete selected
                  </Button>
                </div>
              )}
            </div>

            {notice && <p role="status" className="reveal border-b border-edge bg-surface-2 px-5 py-2.5 text-sm text-ink">{notice}</p>}
            {archive.error && <div className="px-5 pt-3"><ErrorNote message={`${archive.error} Showing the last loaded data.`} /></div>}

            {rows.length === 0 ? (
              <Empty icon={documents.length ? Search : DatabaseIcon}>
                {documents.length ? (query ? `No documents in ${scopeName} match “${query}”.` : "This folder is empty.") : (
                  <>
                    <span>The database is empty.</span>
                    <a className="text-ink underline" href="#/knowledge">Add documents in Knowledge base</a>
                  </>
                )}
              </Empty>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full table-fixed text-sm">
                  <thead className="border-b border-edge bg-surface-2/60 text-xs text-ink-2">
                    <tr>
                      {admin && (
                        <th scope="col" className="w-11 py-2 pl-5">
                          <input
                            ref={selectAll}
                            type="checkbox"
                            className="h-4 w-4 align-middle"
                            style={{ accentColor: "var(--brand)" }}
                            checked={rows.length > 0 && selectedInView === rows.length}
                            onChange={toggleAll}
                            aria-label={`Select all ${plural(rows.length, "document")} in this view`}
                          />
                        </th>
                      )}
                      {columns.map((c) => <SortHeader key={c.key} column={c} sort={sort} onSort={onSort} />)}
                      <th scope="col" className="w-16 py-2 pr-5"><span className="sr-only">Actions</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((d) => {
                      const open = openDoc === d.document_id;
                      const checked = selected.has(d.document_id);
                      return (
                        <Fragment key={d.document_id}>
                          <tr className={`border-b border-edge ${checked ? "bg-surface-2" : "hover:bg-surface-2/60"}`}>
                            {admin && (
                              <td className="py-2.5 pl-5">
                                <input
                                  type="checkbox"
                                  className="h-4 w-4 align-middle"
                                  style={{ accentColor: "var(--brand)" }}
                                  checked={checked}
                                  onChange={() => toggleRow(d.document_id)}
                                  aria-label={`Select ${d.title}`}
                                />
                              </td>
                            )}
                            {columns.map((c) => {
                              switch (c.key) {
                                case "title":
                                  return (
                                    <td key={c.key} className="px-3 py-2.5">
                                      <button
                                        className="flex max-w-full items-center gap-1.5 text-left font-medium text-ink hover:underline"
                                        onClick={() => setOpenDoc(open ? null : d.document_id)}
                                        aria-expanded={open}
                                        title={d.filename ?? d.title}
                                      >
                                        <ChevronRight className={`h-3.5 w-3.5 shrink-0 text-muted transition-transform ${open ? "rotate-90" : ""}`} />
                                        <span className="truncate">{d.title}</span>
                                      </button>
                                      {!showLocation && <div className="truncate pl-5 text-xs text-muted" title={locationLabel(d)}>{locationLabel(d)}</div>}
                                    </td>
                                  );
                                case "location":
                                  return (
                                    <td key={c.key} className="truncate px-3 py-2.5 text-ink-2" title={locationLabel(d)}>
                                      <button className="max-w-full truncate hover:text-ink hover:underline" onClick={() => selectScope(docNodeKey(d))}>
                                        {locationLabel(d)}
                                      </button>
                                    </td>
                                  );
                                case "trust":
                                  return (
                                    <td key={c.key} className="px-3 py-2.5">
                                      <Badge tone={trustTone(d.trust_level)} title={`Source trust ${d.source_trust.toFixed(2)}. ${d.retrieval_reason ?? "Passes the trust gate."}`}>
                                        {d.trust_level.toLowerCase()}
                                      </Badge>
                                    </td>
                                  );
                                case "chunks":
                                  return <td key={c.key} className="tabular px-3 py-2.5 text-right">{formatNumber(d.chunks_total)}</td>;
                                case "quarantined":
                                  return (
                                    <td key={c.key} className="tabular px-3 py-2.5 text-right" style={d.chunks_quarantined ? { color: "var(--critical)", fontWeight: 600 } : { color: "var(--muted)" }}>
                                      {formatNumber(d.chunks_quarantined)}
                                    </td>
                                  );
                                case "size":
                                  return <td key={c.key} className="tabular px-3 py-2.5 text-right text-ink-2">{formatBytes(d.size_bytes)}</td>;
                                default:
                                  return (
                                    <td key={c.key} className="px-3 py-2.5 whitespace-nowrap text-ink-2" title={new Date(d.created_at).toLocaleString()}>
                                      {new Date(d.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}
                                    </td>
                                  );
                              }
                            })}
                            <td className="py-2.5 pr-5 text-right">
                              {admin && (
                                <Button variant="subtle" size="sm" onClick={() => askDelete(`“${d.title}”`, [d])} aria-label={`Delete ${d.title}`}>
                                  <Trash2 className="h-3.5 w-3.5" />
                                </Button>
                              )}
                            </td>
                          </tr>
                          {open && (
                            <tr className="border-b border-edge bg-surface-2/50">
                              <td colSpan={columns.length + (admin ? 2 : 1)} className="reveal px-5 py-4">
                                <ChunkPreview doc={d} onOpenVector={openVector} />
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {rows.length > 0 && (
              <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 text-xs text-muted">
                <span className="tabular">
                  Showing {formatNumber(current * PAGE_SIZE + 1)}–{formatNumber(Math.min((current + 1) * PAGE_SIZE, rows.length))} of {plural(rows.length, "document")}
                </span>
                {pageCount > 1 && (
                  <div className="flex items-center gap-2">
                    <Button variant="ghost" size="sm" disabled={current === 0} onClick={() => setPage(current - 1)} aria-label="Previous page">
                      <ChevronLeft className="h-3.5 w-3.5" />
                    </Button>
                    <span className="tabular">{current + 1} / {pageCount}</span>
                    <Button variant="ghost" size="sm" disabled={current + 1 >= pageCount} onClick={() => setPage(current + 1)} aria-label="Next page">
                      <ChevronRight className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                )}
              </div>
            )}
          </Card>
          )}
        </div>
      </>
    );
  }

  return (
    <div>
      <PageHeader
        title="Database"
        description="Everything in the knowledge base, by section and folder: the documents and the vectors retrieval searches. Sort and search them, open a chunk to read or edit it, and delete what you no longer need."
        actions={
          <div className="flex gap-2">
            <a href="#/knowledge" className="inline-flex items-center gap-1.5 rounded-lg border border-edge bg-surface px-3.5 py-2 text-sm font-medium text-ink transition hover:bg-surface-2">
              <Plus className="h-4 w-4" /> Add documents
            </a>
            <Button variant="ghost" onClick={() => void archive.reload()} aria-label="Refresh">
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>
        }
      />
      {body}
      {pending && (
        <ConfirmDelete
          pending={pending}
          busy={busy}
          error={deleteError}
          onCancel={() => setPending(null)}
          onConfirm={() => void confirmDelete()}
        />
      )}
    </div>
  );
}

import { ChevronLeft, ChevronRight, RotateCcw, Save, Search, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { api, qs } from "../../api";
import { useApi } from "../../hooks";
import type { VectorDetail, VectorEditResult, VectorIndexInfo, VectorPage } from "../../types";
import { Badge, Button, Card, Empty, ErrorNote, formatBytes, formatNumber, inputClass, Meter } from "../ui";
import type { TreeNode } from "./tree";
import { VectorStrip } from "./VectorStrip";

const PAGE_SIZE = 25;
const MAX_CHARS = 8000; // the API's limit for one chunk

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setSettled(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return settled;
}

function Screening({ action, score }: { action: string; score: number }) {
  return action === "FLAG" ? (
    <Badge tone="warning" title={`Firewall score ${score.toFixed(2)}: flagged and stored sanitized`}>sanitized</Badge>
  ) : (
    <Badge tone="good" title={`Firewall score ${score.toFixed(2)}`}>clean</Badge>
  );
}

function backendLabel(info: VectorIndexInfo): string {
  if (info.backend === "pgvector") return "PostgreSQL + pgvector";
  return info.persisted ? "In-memory (on disk)" : "In-memory (not saved)";
}

// ---------------------------------------------------------------- editor
function VectorEditor({
  chunkId,
  admin,
  onSelect,
  onChanged,
  onDeleted,
}: {
  chunkId: string;
  admin: boolean;
  onSelect: (id: string | null) => void;
  onChanged: () => void;
  onDeleted: (label: string) => void;
}) {
  const path = `/api/vectors/${encodeURIComponent(chunkId)}`;
  const res = useApi<VectorDetail>(path);
  // After a save, show what the server stored at once rather than the stale copy.
  const [saved, setSaved] = useState<VectorDetail | null>(null);
  const detail = saved ?? (res.data?.chunk_id === chunkId ? res.data : null);
  const [draft, setDraft] = useState<string | null>(null); // null: untouched
  const [busy, setBusy] = useState<"save" | "delete" | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const text = draft ?? detail?.content ?? "";
  const dirty = detail !== null && draft !== null && draft !== detail.content;
  const label = detail ? `“${detail.document_title}” chunk ${detail.chunk_index + 1}` : "this chunk";
  const top = useRef<HTMLDivElement>(null);

  // Each selection mounts a fresh editor (keyed by chunk id): bring it into view.
  useEffect(() => {
    top.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  async function save() {
    if (!dirty) return;
    setBusy("save");
    setMessage(null);
    try {
      const result = await api.put<VectorEditResult>(path, { content: text });
      setSaved(result.detail);
      setDraft(null);
      setMessage({
        ok: true,
        text: result.sanitized
          ? `Saved. The firewall flagged the new text (${result.categories.join(", ").replaceAll("_", " ").toLowerCase() || "suspicious"}) and stored a sanitized copy. The vector was recomputed.`
          : "Saved. The firewall allowed the new text and the vector was recomputed.",
      });
      onChanged();
    } catch (e) {
      setMessage({ ok: false, text: errorText(e) });
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    setBusy("delete");
    setMessage(null);
    try {
      await api.del(path);
      onDeleted(label);
      onChanged();
    } catch (e) {
      setMessage({ ok: false, text: errorText(e) });
      setBusy(null);
      setConfirming(false);
    }
  }

  return (
    <div ref={top} className="reveal scroll-mt-20">
    <Card
      title={detail ? `${detail.document_title} · chunk ${detail.chunk_index + 1}` : "Vector"}
      subtitle={detail ? `${detail.section} / ${detail.folder} · ${detail.chunk_id}` : chunkId}
      actions={
        <Button variant="subtle" size="sm" onClick={() => onSelect(null)} aria-label="Close vector">
          <X className="h-4 w-4" />
        </Button>
      }
    >
      {!detail ? (
        res.error ? <ErrorNote message={res.error} /> : <p className="text-sm text-muted" role="status">Loading the vector…</p>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_300px]">
          <div className="min-w-0 space-y-6">
            <section aria-labelledby="chunk-text-label">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <h3 id="chunk-text-label" className="text-sm font-semibold text-ink">Chunk text</h3>
                <div className="flex items-center gap-2 text-xs text-muted">
                  <Screening action={detail.firewall_action} score={detail.firewall_score} />
                  <span className="tabular">{formatNumber(text.length)} / {formatNumber(MAX_CHARS)} characters</span>
                </div>
              </div>
              {admin ? (
                <textarea
                  aria-labelledby="chunk-text-label"
                  className={`${inputClass} min-h-48 resize-y font-mono text-xs leading-relaxed`}
                  value={text}
                  maxLength={MAX_CHARS}
                  onChange={(e) => { setDraft(e.target.value); setMessage(null); setConfirming(false); }}
                  disabled={busy !== null}
                />
              ) : (
                <pre className="max-h-72 overflow-auto rounded-lg border border-edge bg-surface-2 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap text-ink-2 [overflow-wrap:anywhere]">{detail.content}</pre>
              )}
              {message && (
                <p role={message.ok ? "status" : "alert"} className="mt-2 rounded-lg border border-edge bg-surface-2 px-3 py-2 text-sm text-ink">
                  <span aria-hidden className="mr-1.5 font-bold">{message.ok ? "✓" : "✕"}</span>
                  {message.text}
                </p>
              )}
              {admin && (
                <>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Button onClick={() => void save()} disabled={!dirty || busy !== null || !text.trim()}>
                      <Save className="h-4 w-4" /> {busy === "save" ? "Screening and re-embedding…" : "Save and re-embed"}
                    </Button>
                    <Button variant="ghost" onClick={() => { setDraft(null); setMessage(null); }} disabled={!dirty || busy !== null}>
                      <RotateCcw className="h-4 w-4" /> Undo changes
                    </Button>
                    <span className="flex-1" />
                    {confirming ? (
                      <span className="flex items-center gap-2" role="group" aria-label="Confirm delete">
                        <span className="text-xs text-ink-2">Remove this vector? It can't be undone.</span>
                        <Button variant="ghost" size="sm" onClick={() => setConfirming(false)} disabled={busy !== null}>Cancel</Button>
                        <Button variant="danger" size="sm" onClick={() => void remove()} disabled={busy !== null}>
                          <Trash2 className="h-3.5 w-3.5" /> {busy === "delete" ? "Deleting…" : "Delete vector"}
                        </Button>
                      </span>
                    ) : (
                      <Button variant="ghost" onClick={() => setConfirming(true)} disabled={busy !== null}>
                        <Trash2 className="h-4 w-4" /> Delete vector
                      </Button>
                    )}
                  </div>
                  <p className="mt-2 text-xs leading-relaxed text-muted">
                    Saving screens the new text with the ingestion firewall and recomputes its vector with {detail.model}. Text the
                    firewall blocks is refused; flagged text is stored sanitized. Deleting removes only this chunk — the document stays.
                  </p>
                </>
              )}
            </section>

            <section aria-labelledby="vector-label">
              <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                <h3 id="vector-label" className="text-sm font-semibold text-ink">Embedding</h3>
                <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
                  <div><dt className="inline text-muted">Model </dt><dd className="inline text-ink-2">{detail.model}</dd></div>
                  <div><dt className="inline text-muted">Dimensions </dt><dd className="tabular inline text-ink-2">{detail.dim}</dd></div>
                  <div><dt className="inline text-muted">Length ‖v‖ </dt><dd className="tabular inline text-ink-2">{detail.norm.toFixed(4)}</dd></div>
                </dl>
              </div>
              <VectorStrip values={detail.vector} />
              <details className="mt-3 text-xs">
                <summary className="cursor-pointer text-ink-2 hover:text-ink">Show all {detail.dim} values</summary>
                <ol className="mt-2 grid max-h-64 grid-cols-2 gap-x-4 gap-y-0.5 overflow-auto rounded-lg border border-edge bg-surface-2 p-3 font-mono sm:grid-cols-4 lg:grid-cols-6">
                  {detail.vector.map((v, i) => (
                    <li key={i} className="flex justify-between gap-2">
                      <span className="text-muted">{i}</span>
                      <span className="tabular text-ink-2">{v.toFixed(5)}</span>
                    </li>
                  ))}
                </ol>
              </details>
            </section>
          </div>

          <section aria-labelledby="neighbours-label" className="min-w-0">
            <h3 id="neighbours-label" className="text-sm font-semibold text-ink">Nearest neighbours</h3>
            <p className="mt-0.5 mb-3 text-xs text-muted">The chunks retrieval would rank closest to this one (cosine similarity).</p>
            {detail.neighbours.length ? (
              <ol className="space-y-2">
                {detail.neighbours.map((n) => (
                  <li key={n.chunk_id}>
                    <button
                      onClick={() => onSelect(n.chunk_id)}
                      className="w-full rounded-lg border border-edge p-3 text-left transition hover:bg-surface-2"
                    >
                      <div className="flex items-baseline justify-between gap-2">
                        <strong className="tabular text-sm font-semibold text-ink">{n.similarity.toFixed(3)}</strong>
                        <span className="truncate text-xs text-ink-2">{n.document_title} · #{n.chunk_index + 1}</span>
                      </div>
                      <div className="mt-1.5"><Meter value={n.similarity} label={`Similarity ${n.similarity.toFixed(3)}`} /></div>
                      <p className="mt-1.5 line-clamp-2 text-xs text-muted [overflow-wrap:anywhere]">{n.preview}</p>
                    </button>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-xs text-muted">This is the only vector in the index.</p>
            )}
          </section>
        </div>
      )}
    </Card>
    </div>
  );
}

// ------------------------------------------------------------------ list
export default function VectorPanel({
  scope,
  scopeTitle,
  admin,
  selectedId,
  onSelect,
  onChanged,
}: {
  scope: TreeNode;
  scopeTitle: ReactNode;
  admin: boolean;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onChanged: () => void;
}) {
  const info = useApi<VectorIndexInfo>("/api/vectors/info");
  const [query, setQuery] = useState("");
  const search = useDebounced(query.trim(), 300);
  const [action, setAction] = useState<"" | "ALLOW" | "FLAG">("");
  const [offset, setOffset] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => setOffset(0), [scope.key, search, action]);

  const page = useApi<VectorPage>(
    `/api/vectors${qs({
      section: scope.kind === "root" ? undefined : scope.section,
      folder: scope.kind === "folder" ? scope.path : undefined,
      q: search,
      action,
      offset,
      limit: PAGE_SIZE,
    })}`,
  );
  const items = page.data?.items ?? [];
  const total = page.data?.total ?? 0;

  function changed() {
    void info.reload();
    void page.reload();
    onChanged();
  }

  return (
    <div className="reveal space-y-6">
      <Card title={scopeTitle} subtitle="The vector index: every indexed chunk with the embedding retrieval searches. Pick one to read, edit or delete it.">
        <dl className="mb-4 grid grid-cols-2 gap-3 rounded-lg border border-edge bg-surface-2 p-3 text-xs sm:grid-cols-3 xl:grid-cols-5" aria-busy={!info.data}>
          {[
            ["Storage", info.data ? backendLabel(info.data) : "…"],
            ["Embedding model", info.data?.embedder ?? "…"],
            ["Dimensions", info.data ? formatNumber(info.data.dim) : "…"],
            ["Vectors", info.data ? formatNumber(info.data.vectors) : "…"],
            ["Index size", info.data ? formatBytes(info.data.size_bytes) : "…"],
          ].map(([k, v]) => (
            <div key={k} className="min-w-0">
              <dt className="text-muted">{k}</dt>
              <dd className="mt-0.5 truncate font-medium text-ink" title={v}>{v}</dd>
            </div>
          ))}
        </dl>

        <div className="mb-3 flex flex-wrap items-center gap-3">
          <label className="relative min-w-[200px] flex-1">
            <span className="sr-only">Search chunk text</span>
            <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted" />
            <input className={`${inputClass} pl-9`} placeholder="Search chunk text…" value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
          <div className="shrink-0">
            <label className="sr-only" htmlFor="vec-filter">Screening result</label>
            <select id="vec-filter" className={`${inputClass} py-2 pr-8`} value={action} onChange={(e) => setAction(e.target.value as typeof action)}>
              <option value="">All vectors</option>
              <option value="ALLOW">Clean only</option>
              <option value="FLAG">Sanitized only</option>
            </select>
          </div>
        </div>

        {notice && <p role="status" className="mb-3 rounded-lg border border-edge bg-surface-2 px-3 py-2 text-sm text-ink">{notice}</p>}
        <ErrorNote message={page.error} />

        <div className="-mx-5 overflow-x-auto border-t border-edge">
          {!page.data && page.loading ? (
            <p className="px-5 py-8 text-sm text-ink-2" role="status">Loading vectors…</p>
          ) : items.length === 0 ? (
            <Empty icon={Search}>{search ? `No chunk text matches “${search}”.` : "No vectors here."}</Empty>
          ) : (
            <table className="w-full table-fixed text-sm">
              <thead className="border-b border-edge bg-surface-2/60 text-xs text-ink-2">
                <tr>
                  <th scope="col" className="w-[38%] px-5 py-2 text-left font-semibold sm:w-[30%]">Chunk</th>
                  <th scope="col" className="hidden px-3 py-2 text-left font-semibold sm:table-cell">Text</th>
                  <th scope="col" className="w-[104px] px-3 py-2 text-left font-semibold">Screening</th>
                  <th scope="col" className="hidden w-[88px] px-5 py-2 text-right font-semibold md:table-cell">Chars</th>
                </tr>
              </thead>
              <tbody>
                {items.map((v) => {
                  const active = v.chunk_id === selectedId;
                  return (
                    <tr
                      key={v.chunk_id}
                      onClick={() => onSelect(active ? null : v.chunk_id)}
                      className={`cursor-pointer border-b border-edge align-top ${active ? "bg-surface-2" : "hover:bg-surface-2/60"}`}
                    >
                      <td className="px-5 py-2.5">
                        <button
                          className="block max-w-full truncate text-left font-medium text-ink hover:underline"
                          onClick={(e) => { e.stopPropagation(); onSelect(active ? null : v.chunk_id); }}
                          aria-pressed={active}
                          title={v.document_title}
                        >
                          {v.document_title} <span className="tabular font-normal text-muted">#{v.chunk_index + 1}</span>
                        </button>
                        <div className="truncate text-xs text-muted" title={`${v.section} / ${v.folder}`}>{v.section} / {v.folder}</div>
                      </td>
                      <td className="hidden px-3 py-2.5 sm:table-cell">
                        <p className="line-clamp-2 text-xs text-ink-2 [overflow-wrap:anywhere]">{v.preview}</p>
                      </td>
                      <td className="px-3 py-2.5"><Screening action={v.firewall_action} score={v.firewall_score} /></td>
                      <td className="tabular hidden px-5 py-2.5 text-right text-ink-2 md:table-cell">{formatNumber(v.characters)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {total > 0 && (
          <div className="-mb-1 flex flex-wrap items-center justify-between gap-3 pt-3 text-xs text-muted">
            <span className="tabular">
              Showing {formatNumber(offset + 1)}–{formatNumber(Math.min(offset + PAGE_SIZE, total))} of {formatNumber(total)} vectors
            </span>
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} aria-label="Previous vectors">
                <ChevronLeft className="h-3.5 w-3.5" />
              </Button>
              <span className="tabular">{formatNumber(Math.floor(offset / PAGE_SIZE) + 1)} / {formatNumber(Math.max(1, Math.ceil(total / PAGE_SIZE)))}</span>
              <Button variant="ghost" size="sm" disabled={!page.data?.has_more} onClick={() => setOffset(offset + PAGE_SIZE)} aria-label="Next vectors">
                <ChevronRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        )}
      </Card>

      {selectedId && (
        <VectorEditor
          key={selectedId}
          chunkId={selectedId}
          admin={admin}
          onSelect={(id) => { setNotice(null); onSelect(id); }}
          onChanged={changed}
          onDeleted={(label) => { setNotice(`Deleted the vector for ${label}.`); onSelect(null); }}
        />
      )}
    </div>
  );
}

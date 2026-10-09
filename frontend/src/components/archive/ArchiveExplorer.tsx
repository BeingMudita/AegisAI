import { Fragment, useMemo, useRef, useState, type FormEvent } from "react";
import { ArrowLeft, ChevronLeft, ChevronRight, RefreshCw, Search } from "lucide-react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { useApi } from "../../hooks";
import type { ArchiveChunkPage, ArchiveDocument } from "../../types";
import ArchiveScene, { type SceneEntry } from "./ArchiveScene";
import { countArchive, statusLabels } from "./model";
import { buildTree, directDocuments, findNode, pathTo, type TreeNode } from "./tree";
import "./archive.css";

const stages = ["Archive terrain", "Document anatomy", "Document lineage"];
const fmt = (n: number | null) => n === null ? "Unavailable" : n.toLocaleString();
const plural = (n: number, word: string) => `${n.toLocaleString()} ${word}${n === 1 ? "" : "s"}`;
const FILES = "\u0000files"; // the extra layer for files filed directly in a folder that also has subfolders

function LocationForm({ document, onSaved }: { document: ArchiveDocument; onSaved: () => void }) {
  const [section, setSection] = useState(document.section);
  const [folder, setFolder] = useState(document.folder);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      await api.put(`/api/retrieval/documents/${encodeURIComponent(document.document_id)}/location`, { section: section.trim(), folder: folder.trim() });
      onSaved();
    } catch (e) { setError(e instanceof Error ? e.message : "Could not organize this document."); }
    finally { setBusy(false); }
  }
  return <details className="aj-organize"><summary>Organize this document</summary><form onSubmit={save}>
    <label>Section<input required maxLength={80} value={section} onChange={e => setSection(e.target.value)} /></label>
    <label>Folder<input required maxLength={1024} value={folder} onChange={e => setFolder(e.target.value)} /></label>
    <button className="aj-control" disabled={busy || !section.trim() || !folder.trim()}>{busy ? "Saving…" : "Save location"}</button>
    {error && <p role="alert">{error}</p>}
  </form></details>;
}

export default function ArchiveExplorer() {
  const { user } = useAuth();
  const archive = useApi<ArchiveDocument[]>("/api/retrieval/archive", 10000);
  // Where we are in the same section → folder → subfolder tree the Database page shows.
  const [nodeKey, setNodeKey] = useState("");
  // A folder holding both subfolders and its own files lists the files as one extra layer.
  const [filesOnly, setFilesOnly] = useState(false);
  const [documentId, setDocumentId] = useState<string | null>(null);
  const [chunkIndex, setChunkIndex] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState(0);
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState("");
  const titleRef = useRef<HTMLHeadingElement>(null);
  const tree = useMemo(() => buildTree(archive.data ?? []), [archive.data]);
  const node = findNode(tree, nodeKey) ?? tree;
  const trail = pathTo(tree, node.key);
  const direct = directDocuments(node);
  const stage = node.kind === "root" ? 0 : node.children.length && !filesOnly ? 1 : 2;
  const scope = stage === 2 ? direct : node.documents;
  const document = stage === 2 ? direct.find(d => d.document_id === documentId) : undefined;
  const chunkRequest = useApi<ArchiveChunkPage>(document ? `/api/retrieval/documents/${encodeURIComponent(document.document_id)}/archive-chunks?offset=${offset}&limit=12` : null, 10000);
  // A path change may retain the previous hook value for one render. Never show it under a different document.
  const chunkPage = chunkRequest.data?.document_id === document?.document_id && chunkRequest.data?.offset === offset ? chunkRequest.data : null;
  const chunks = chunkPage?.chunks ?? [];
  const chunk = chunks.find(c => c.chunk_index === chunkIndex);
  const counts = countArchive(scope);
  const scopeName = node.kind === "root" ? "Entire archive" : trail.slice(1).map(n => n.name).join(" / ") + (filesOnly ? " / Files" : "");
  const eligibility = (docs: ArchiveDocument[]) => {
    const c = countArchive(docs);
    return `${fmt(c.eligible)} eligible · ${fmt(c.blocked + c.low)} withheld`;
  };
  const mix = (docs: ArchiveDocument[]) => {
    const { ready, sanitized, low, blocked } = countArchive(docs);
    return { ready, sanitized, low, blocked };
  };
  const folderDetail = (n: TreeNode) => n.children.length
    ? `${plural(n.children.length, "folder")} · ${plural(n.documents.length, "doc")}`
    : `${plural(n.documents.length, "doc")} · ${countArchive(n.documents).chunks.toLocaleString()} chunks`;
  const entries: SceneEntry[] = stage === 0
    ? tree.children.map(s => ({ id: s.key, name: s.name, count: s.children.length, detail: folderDetail(s), eligibility: eligibility(s.documents), mix: mix(s.documents) }))
    : stage === 1
      ? [
        ...(direct.length ? [{ id: FILES, name: `Files in ${node.name}`, count: direct.length, detail: `${plural(direct.length, "doc")} not in a subfolder`, eligibility: eligibility(direct), mix: mix(direct) }] : []),
        ...node.children.map(f => ({ id: f.key, name: f.name, count: f.documents.length, detail: folderDetail(f), eligibility: eligibility(f.documents), mix: mix(f.documents) })),
      ]
      : scope.map(d => ({ id: d.document_id, name: d.title, count: d.chunks_total, detail: `${d.chunks_total.toLocaleString()} chunks · ${d.chunks_quarantined} blocked`, eligibility: eligibility([d]), mix: mix([d]) }));
  const matches = entries.filter(e => e.name.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  const pageSize = stage === 0 ? 6 : stage === 1 ? 5 : 4;
  const pageCount = Math.max(1, Math.ceil(matches.length / pageSize));
  const currentPage = Math.min(page, pageCount - 1);
  const visible = matches.slice(currentPage * pageSize, (currentPage + 1) * pageSize);
  const selectedVisible = visible.some(e => e.id === documentId);
  const entryLabel = stage === 0 ? "sections" : stage === 1 ? "folders" : "documents";
  function clearSelection() { setDocumentId(null); setChunkIndex(null); setOffset(0); setPage(0); setQuery(""); }
  function focusTitle() { requestAnimationFrame(() => titleRef.current?.focus({ preventScroll: true })); }
  function goTo(key: string, files = false) {
    clearSelection();
    setNodeKey(key);
    setFilesOnly(files);
    focusTitle();
  }
  function goBack() {
    if (filesOnly) goTo(node.key);
    else goTo(trail[trail.length - 2]?.key ?? "");
  }
  function navigateStep(to: number) {
    if (to === 0) goTo("");
    else if (to === 1) goTo(trail[1]?.key ?? "");
    else { clearSelection(); focusTitle(); }
  }
  function selectEntry(id: string) {
    setChunkIndex(null); setOffset(0); setNotice("");
    if (stage === 2) setDocumentId(current => current === id ? null : id);
    else if (id === FILES) goTo(node.key, true);
    else goTo(id);
  }
  const where = node.kind === "section" ? "section" : "folder";
  const backTo = filesOnly ? node.name : trail[trail.length - 2]?.kind === "root" ? "all sections" : trail[trail.length - 2]?.name;
  const headline = stage === 0 ? "Your archive. Every section, in view." : stage === 1 ? `${node.name}, layer by layer.` : `${filesOnly ? `Files in ${node.name}` : node.name} → documents`;
  const subtitle = stage === 0
    ? "Each block is a section. Open one to reveal its folders."
    : stage === 1
      ? `${plural(node.children.length, "folder")} inside this ${where}${direct.length ? `, plus ${plural(direct.length, "document")} filed directly in it` : ""}. Select a layer to open it.`
      : `${plural(scope.length, "document")} in this ${where}. Select a document to reveal its chunks.`;
  return <section className="archive-explorer" aria-label="Knowledge explorer">
    <div className="aj-pagehead"><h2>Knowledge explorer</h2><div className="aj-actions"><a className="aj-control" href="#/knowledge">Add documents ↗</a><button className="aj-control" onClick={() => { void archive.reload(); void chunkRequest.reload(); }} aria-label="Refresh archive"><RefreshCw size={14} /></button></div></div>
    <nav className="aj-crumbs" aria-label="Archive breadcrumb">{trail.map((n, i) => {
      const label = i === 0 ? "Archive" : n.name;
      return <Fragment key={n.key}>{i > 0 && <span>/</span>}{i === trail.length - 1 && !filesOnly ? <span aria-current="page">{label}</span> : <button onClick={() => goTo(n.key)}>{label}</button>}</Fragment>;
    })}{filesOnly && <><span>/</span><span aria-current="page">Files</span></>}</nav>
    <ol className="aj-steps">{stages.map((label, i) => <li key={label} className={stage === i ? "aj-current" : ""}><button disabled={i > stage} onClick={() => navigateStep(i)} aria-current={stage === i ? "step" : undefined}><span className="aj-step-num">0{i + 1}</span><span><b>{label}</b><small>{["Sections in your archive", "Folders and subfolders", "Documents and their chunks"][i]}</small></span></button></li>)}</ol>
    {archive.error && <div className="aj-message" role="alert">{archive.error} {archive.data ? "Showing the last loaded archive." : "The archive could not load."}<button className="aj-control" onClick={() => void archive.reload()}>Try again</button></div>}
    {notice && <p className="aj-message" role="status">{notice}</p>}
    {!archive.data && archive.loading ? <div className="aj-empty" role="status">Loading your archive…</div> : archive.data?.length === 0 ? <div className="aj-empty"><span className="aj-empty-stack" aria-hidden="true">▱<br />▱<br />▱</span><h3>Your archive starts here.</h3><p>Add documents and choose a section and folder. Your real archive will take shape here.</p><a className="aj-control" href="#/knowledge">Add your first documents ↗</a></div> : archive.data && <>
      <div className="aj-dashboard">
        <aside className="aj-sidebar" aria-label="Current scope summary">
          <div className="aj-paper"><small>Chunks eligible for RAG</small><strong>{fmt(counts.eligible)} <span>/ {fmt(counts.chunks)}</span></strong><small>Includes {fmt(counts.sanitized)} sanitized</small><small className="aj-paper-scope">{scopeName}</small></div>
          <div className="aj-scope"><div className="aj-statrow"><span><i className="aj-mark blocked" /> Blocked</span><b>{fmt(counts.blocked)}</b></div><div className="aj-statrow"><span><i className="aj-mark low" /> Low trust</span><b>{fmt(counts.low)}</b></div><div className="aj-meter" aria-hidden="true">{Object.keys(statusLabels).map(key => <span key={key} className={key} style={{ flex: counts[key as keyof typeof statusLabels] }} />)}</div><div className="aj-statrow"><span>Documents</span><b>{fmt(counts.docs)}</b></div><div className="aj-statrow"><span>{entryLabel}</span><b>{entries.length}</b></div></div>
          <div className="aj-directory"><div className="aj-listtitle"><span>In this view</span><span>{visible.length}</span></div>{visible.map(entry => <button key={entry.id} className={`aj-item ${documentId === entry.id ? "aj-selected" : ""}`} onClick={() => selectEntry(entry.id)}><span className="aj-mini-stack" aria-hidden="true" /><span><b>{entry.name}</b><small>{entry.detail}</small></span></button>)}</div>
        </aside>
        <div className="aj-content">
          <section className="aj-stage" aria-labelledby="archive-stage-title">
            <div className="aj-stagehead"><div><span className="aj-eyebrow">0{stage + 1} / {stages[stage]}</span><h3 id="archive-stage-title" ref={titleRef} tabIndex={-1}>{headline}</h3><p className="aj-subtitle">{subtitle}</p></div>{stage > 0 && <button className="aj-back" onClick={goBack} aria-label={`Back to ${backTo}`}><ArrowLeft size={14} /> Back</button>}</div>
            <div className="aj-toolbar"><label className="aj-search"><Search size={13} /><input aria-label={`Find ${entryLabel}`} placeholder={`Find ${entryLabel}…`} value={query} onChange={e => { setQuery(e.target.value); setPage(0); setDocumentId(null); setChunkIndex(null); }} /></label><span>{fmt(matches.length)} {entryLabel}</span></div>
            {visible.length ? <ArchiveScene key={`${stage}-${node.key}-${filesOnly}`} stage={stage} entries={visible} rootName={node.kind === "root" ? "Archive" : node.name} selectedDocument={selectedVisible ? documentId : null} selectedChunk={chunkIndex} chunks={selectedVisible ? chunks : []} onEntry={selectEntry} onChunk={setChunkIndex} chunkMessage={chunkRequest.error ? "Chunks unavailable. Retry below." : document && !chunkPage ? "Loading chunks…" : document ? "No stored chunks in this range." : ""} /> : <p className="aj-empty">No {entryLabel} match “{query}”.</p>}
            <div className="aj-stagefoot"><span className="aj-scene-caption">{["Spatial view", "Exploded view", "Branching view"][stage]}</span><div className="aj-pagination"><button className="aj-control" aria-label={`Previous ${entryLabel}`} disabled={currentPage === 0} onClick={() => { setPage(currentPage - 1); setDocumentId(null); setChunkIndex(null); }}><ChevronLeft size={14} /></button><span>{currentPage + 1} / {pageCount}</span><button className="aj-control" aria-label={`Next ${entryLabel}`} disabled={currentPage + 1 >= pageCount} onClick={() => { setPage(currentPage + 1); setDocumentId(null); setChunkIndex(null); }}><ChevronRight size={14} /></button></div></div>
            {document && <div className="aj-stagefoot"><span>{chunkPage ? `Chunks ${Math.min(offset + 1, chunkPage.total)}–${Math.min(offset + 12, chunkPage.total)} of ${fmt(chunkPage.total)}` : "Loading chunk details…"}</span><div className="aj-pagination"><button className="aj-control" disabled={offset === 0} onClick={() => { setOffset(Math.max(0, offset - 12)); setChunkIndex(null); }} aria-label="Previous chunks">←</button><button className="aj-control" disabled={!chunkPage?.has_more} onClick={() => { setOffset(offset + 12); setChunkIndex(null); }} aria-label="Next chunks">→</button></div></div>}
          </section>
          {document && chunkRequest.error && <div className="aj-message" role="alert">{chunkRequest.error}<button className="aj-control" onClick={() => void chunkRequest.reload()}>Retry chunks</button></div>}
          <section className="aj-inspector" aria-label="Selection details" aria-live="polite">
            {chunk && document ? <div className="aj-chunk-detail"><div><span className="aj-eyebrow">Chunk {chunk.chunk_index + 1} / {document.title}</span><h4>{chunk.excerpt_only ? "Stored excerpt" : chunk.firewall_action === "FLAG" ? "Sanitized passage" : "Stored passage"}</h4><pre className="aj-preview-text">{chunk.content}</pre>{chunk.excerpt_only && <p>Only an excerpt was retained for this quarantined chunk. Size values describe the original chunk where available.</p>}<div className="aj-chunk-meta"><span><b>{fmt(chunk.word_count)}</b> words</span><span><b>{fmt(chunk.size_bytes)}</b> bytes</span><span><b>{fmt(chunk.estimated_tokens)}</b> estimated tokens (characters ÷ 4)</span></div></div><div className="aj-decision"><span className="aj-badge"><i className={`aj-mark ${chunk.status}`} />{statusLabels[chunk.status]}</span><p>{chunk.reason}</p><p>Indexed: {chunk.indexed ? "Yes" : "No"}<br />Firewall score: {chunk.firewall_score.toFixed(2)}</p>{chunk.categories.length > 0 && <p>Signals: {chunk.categories.join(", ").replaceAll("_", " ")}</p>}</div></div> : <div className="aj-overview-detail"><div><span className="aj-eyebrow">{document ? "Document structure" : "Archive structure"}</span><h4>{document?.title ?? "Section → folder → document → chunk"}</h4><p>{document ? "Each branch is one chunk. Select one to inspect its content, size, and retrieval decision." : stage === 0 ? "Move from your whole archive down to a single passage. Open a section to begin." : stage === 1 ? "One layer represents one folder. Open it to see the documents inside." : "Each branch represents a document. Open one to see its chunks."}</p>{document && <p>Source: {document.source} · Trust: {document.source_trust.toFixed(2)}<br />{document.retrieval_reason ?? "This source passes the current trust gate."}</p>}</div><div className="aj-detail-totals"><div><strong>{document ? 1 : fmt(counts.docs)}</strong><span>documents</span></div><div><strong>{fmt(document?.chunks_total ?? counts.chunks)}</strong><span>chunks</span></div></div></div>}
            {document && user?.role === "ADMIN" && <LocationForm key={document.document_id} document={document} onSaved={() => { goTo(""); setNotice("Document location saved."); void archive.reload(); }} />}
          </section>
        </div>
      </div>
      <footer className="aj-footer"><div className="aj-legend">{Object.entries(statusLabels).map(([status, label]) => <span key={status}><i className={`aj-mark ${status}`} />{label}</span>)}</div><span>Live archive · refreshes every 10 seconds</span></footer>
      <p className="aj-footnote">Eligibility reflects ingestion screening and current source trust. Retrieval still checks query relevance and screens content again. Blocks and layers represent groups; their size is illustrative.</p>
    </>}
  </section>;
}

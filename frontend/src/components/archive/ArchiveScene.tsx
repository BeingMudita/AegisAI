import { useEffect, useId, useRef, useState } from "react";
import type { ArchiveChunk, ArchiveStatus } from "../../types";
import { statusLabels } from "./model";

export type StatusMix = Record<ArchiveStatus, number>;
export interface SceneEntry { id: string; name: string; detail: string; count: number; eligibility: string; mix?: StatusMix }

const STATUS_STROKE: Record<ArchiveStatus, string> = {
  ready: "var(--good)", sanitized: "var(--warning)", low: "var(--serious)", blocked: "var(--critical)",
};

/** A thin stacked bar: how this group's chunks split across the status scale. */
function Mix({ mix }: { mix?: StatusMix }) {
  const parts = mix ? (Object.keys(statusLabels) as ArchiveStatus[]).filter(k => mix[k] > 0) : [];
  if (!mix || !parts.length) return null;
  return <span className="aj-mix" aria-hidden="true">{parts.map(k => <span key={k} className={k} style={{ flexGrow: mix[k] }} title={`${statusLabels[k]}: ${mix[k].toLocaleString()} chunks`} />)}</span>;
}
interface Props {
  stage: number;
  entries: SceneEntry[];
  rootName: string;
  selectedDocument: string | null;
  selectedChunk: number | null;
  chunks: ArchiveChunk[];
  onEntry: (id: string) => void;
  onChunk: (index: number) => void;
  chunkMessage: string;
}

function Plate({ x, y, width, label, layers = 1 }: { x: number; y: number; width: number; label: string; layers?: number }) {
  const depth = width * .46;
  return <g transform={`translate(${x} ${y})`}>
    {Array.from({ length: layers }, (_, i) => {
      const offset = (layers - 1 - i) * 8;
      return <g key={i} transform={`translate(0 ${offset})`}>
        <path d={`M${-width / 2},0 L0,${depth / 2} L${width / 2},0 v8 L0,${depth / 2 + 8} L${-width / 2},8 Z`} fill="#565656" stroke="#8c8c8c" strokeWidth=".7" />
        <path d={`M0,${-depth / 2} L${width / 2},0 L0,${depth / 2} L${-width / 2},0 Z`} fill={i === layers - 1 ? "#dedede" : "#999"} stroke="#ededed" strokeWidth=".7" />
        {i === layers - 1 && <><path d={`M0,${-depth * .34} L${width * .34},0 L0,${depth * .34} L${-width * .34},0 Z`} fill="none" stroke="#888" strokeWidth=".6" /><text y="3" fill="#333" textAnchor="middle" fontSize="9" fontFamily="monospace">{label}</text></>}
      </g>;
    })}
  </g>;
}

const curve = (x: number, y: number, tx: number, ty: number) => `M${x},${y} C${x + (tx - x) * .55},${y} ${x + (tx - x) * .45},${ty} ${tx},${ty}`;

export default function ArchiveScene({ stage, entries, rootName, selectedDocument, selectedChunk, chunks, onEntry, onChunk, chunkMessage }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  const pattern = useId();
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const small = width < 540;
  const columns = width < 400 ? 2 : 3;
  const terrainHeight = Math.max(350, Math.ceil(entries.length / columns) * 185 + 45);
  const folderHeight = Math.max(380, entries.length * 100 + 70);
  let cursor = 95;
  const docPositions = entries.map((entry, i) => {
    const y = small ? cursor : 72 + i * 97;
    if (small) cursor += 90 + (entry.id === selectedDocument ? Math.max(chunks.length * 54, 70) : 0);
    return { ...entry, x: small ? 30 : width * .25, y, w: small ? width - 62 : width * .30 };
  });
  const openDoc = docPositions.find(d => d.id === selectedDocument);
  const chunkPositions = chunks.map((chunk, i) => ({
    chunk, x: small ? 60 : width * .69, y: small ? (openDoc?.y ?? 0) + 78 + i * 54 : 58 + i * 54, w: small ? width - 85 : width * .28,
  }));
  const height = stage === 0 ? terrainHeight : stage === 1 ? folderHeight : small ? Math.max(350, cursor + 20) : Math.max(430, chunks.length * 54 + 100);
  return <div ref={ref} className="aj-scene" style={{ height }}>
    <svg className="aj-scene-art" width="100%" height="100%" aria-hidden="true">
      <defs><pattern id={pattern} width="32" height="32" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".6" fill="#555" /></pattern></defs>
      <rect width="100%" height="100%" fill={`url(#${pattern})`} opacity=".3" />
      {stage < 2 && <g opacity=".12" fill="none" stroke="#bbb">{Array.from({ length: 10 }, (_, i) => <ellipse key={i} cx={width * .5} cy={height * .64} rx={70 + i * 32} ry={25 + i * 17} />)}</g>}
      {stage === 0 && entries.map((entry, i) => <g key={entry.id} className="aj-block-enter" style={{ animationDelay: `${i * 55}ms` }}><Plate x={width / columns * (i % columns + .5)} y={78 + Math.floor(i / columns) * 185 + (i % columns === 1 ? 20 : 0)} width={Math.min(120, width / columns * .63)} layers={Math.min(7, entry.count + 2)} label={String(i + 1).padStart(2, "0")} /></g>)}
      {stage === 1 && entries.map((entry, i) => <g key={entry.id} className="aj-layer-enter" style={{ animationDelay: `${i * 60}ms` }}><Plate x={width * .30} y={75 + i * 100} width={Math.min(250, width * .43)} label={`FOLDER ${String(i + 1).padStart(2, "0")}`} /><path d={`M${width * .30 + Math.min(250, width * .43) / 2},${79 + i * 100} H${width * .54}`} stroke="#999" /></g>)}
      {stage === 2 && <g fill="none" stroke="#666" strokeWidth="1">
        {docPositions.map(doc => <path key={doc.id} className="aj-branch-enter" d={small ? `M18,55 V${doc.y + 27} H30` : curve(width * .18, 198, doc.x, doc.y + 28)} />)}
        {openDoc && chunkPositions.map(({ chunk, x, y }) => <path key={`${openDoc.id}-${chunk.chunk_index}`} className="aj-branch-enter" d={small ? `M45,${openDoc.y + 57} V${y + 21} H${x}` : curve(openDoc.x + openDoc.w, openDoc.y + 28, x, y + 21)} stroke={chunk.chunk_index === selectedChunk ? "#eee" : STATUS_STROKE[chunk.status]} strokeOpacity={chunk.chunk_index === selectedChunk ? 1 : .7} strokeDasharray={chunk.status === "blocked" ? "4 4" : chunk.status === "low" ? "1 4" : undefined} />)}
      </g>}
    </svg>
    <div className="aj-nodes">
      {stage === 0 && entries.map((entry, i) => <button key={entry.id} className="aj-terrain-node" title={`${entry.name}: ${entry.eligibility}`} style={{ left: width / columns * (i % columns + .5) - Math.min(180, width / columns) / 2, top: 30 + Math.floor(i / columns) * 185 + (i % columns === 1 ? 20 : 0), width: Math.min(180, width / columns) }} onClick={() => onEntry(entry.id)} aria-label={`Open section ${entry.name}`}><b>{entry.name}</b><small>{entry.detail}</small><small>{entry.eligibility}</small><Mix mix={entry.mix} /></button>)}
      {stage === 1 && entries.map((entry, i) => <button key={entry.id} className="aj-folder-node" style={{ left: width * .54, top: 48 + i * 100, width: width * .43 }} onClick={() => onEntry(entry.id)} aria-label={`Open folder ${entry.name}`}><span><b>{entry.name}</b><small>{entry.detail}</small><small>{entry.eligibility}</small><Mix mix={entry.mix} /></span></button>)}
      {stage === 2 && <>
        <div className="aj-tree-root" style={{ left: small ? 14 : 12, top: small ? 15 : 170, width: small ? width - 45 : width * .18 - 12 }}><b>{rootName}</b><small>Folder</small></div>
        {!small && <><span className="aj-column-label" style={{ left: width * .25 }}>Documents</span><span className="aj-column-label" style={{ left: width * .69 }}>Chunks</span></>}
        {docPositions.map(doc => <button key={doc.id} className="aj-doc-node" style={{ left: doc.x, top: doc.y, width: doc.w }} onClick={() => onEntry(doc.id)} aria-expanded={doc.id === selectedDocument}><b>{doc.name}</b><small>{doc.detail}</small><Mix mix={doc.mix} /></button>)}
        {openDoc && chunkPositions.map(({ chunk, x, y, w }) => <button key={`${openDoc.id}-${chunk.chunk_index}`} className="aj-chunk-node aj-chunk-enter" data-status={chunk.status} style={{ left: x, top: y, width: w }} onClick={() => onChunk(chunk.chunk_index)} aria-pressed={chunk.chunk_index === selectedChunk} aria-label={`Chunk ${chunk.chunk_index + 1}: ${statusLabels[chunk.status]}`}><i className={`aj-mark ${chunk.status}`} /><span><b>{String(chunk.chunk_index + 1).padStart(3, "0")} · {statusLabels[chunk.status]}</b><small>{chunk.word_count === null ? "Size unavailable" : `${chunk.word_count.toLocaleString()} words`}</small></span></button>)}
        {!chunks.length && <p className="aj-tree-hint" role="status" style={{ left: small ? 65 : width * .69, top: small ? (openDoc?.y ?? 150) + 85 : 145 }}>{chunkMessage || "Open a document to reveal its chunks."}</p>}
      </>}
    </div>
  </div>;
}

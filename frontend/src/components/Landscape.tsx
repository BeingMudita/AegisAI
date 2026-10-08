import { Boxes, ShieldAlert } from "lucide-react";
import { useMemo } from "react";

import type { DocumentChunkView, IngestReport, KbStats, TrustLevel } from "../types";
import { formatNumber } from "./ui";

/* The knowledge landscape — a spatial, isometric read of the real index. Each
   document is a stack of plates (one per chunk, proportionally): clean indexed
   plates carry the document's trust color, sanitized plates are amber, and
   quarantined plates float above a gap because they never entered the index.
   Everything here is computed from live /api/retrieval data — no mock values. */

const TRUST_COLOR: Record<TrustLevel, string> = {
  VERIFIED: "#4f8a52",
  HIGH: "#74a567",
  MEDIUM: "#9bb089",
  LOW: "#c3a45e",
  UNTRUSTED: "#cf6a52",
};
const FLAGGED = "#ca9a3e";
const HELD = "#cf6a52";

const TW = 112; // plate width
const TH = 54; // plate height (diamond)
const STEP = 15; // vertical offset per plate — large enough that layers read
const CAP = 14; // max plates drawn per stack
const GAP = 24; // gap under floating quarantined plates
const HW = 124; // horizontal spacing per isometric unit
const HH = 72; // vertical spacing per isometric unit (depth)

type Plate = { color: string; held?: boolean };

function stackHeight(doc: IngestReport): number {
  const { plates: ps } = plates(doc);
  const anyHeld = ps.some((p) => p.held);
  return (ps.length - 1) * STEP + (anyHeld ? GAP : 0) + TH;
}

function plates(doc: IngestReport): { plates: Plate[]; overflow: number } {
  const clean = Math.max(0, doc.chunks_indexed - doc.chunks_flagged);
  const flagged = doc.chunks_flagged;
  const held = doc.chunks_quarantined;
  const total = clean + flagged + held || 1;
  const scale = total > CAP ? CAP / total : 1;
  const n = (x: number) => Math.round(x * scale);
  const color = TRUST_COLOR[doc.trust_level] ?? "#a6bd57";
  const out: Plate[] = [];
  for (let i = 0; i < n(clean); i++) out.push({ color });
  for (let i = 0; i < n(flagged); i++) out.push({ color: FLAGGED });
  for (let i = 0; i < n(held); i++) out.push({ color: HELD, held: true });
  if (out.length === 0) out.push({ color });
  return { plates: out, overflow: total > CAP ? total - out.length : 0 };
}

function Diamond({ color, faded }: { color: string; faded?: boolean }) {
  return (
    <div
      className="absolute left-0"
      style={{
        width: TW,
        height: TH,
        clipPath: "polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)",
        background: `linear-gradient(135deg, color-mix(in srgb, ${color} 94%, white), color-mix(in srgb, ${color} 52%, #243a28))`,
        boxShadow: `inset 0 2px 0 color-mix(in srgb, ${color} 60%, white), inset 0 -10px 14px color-mix(in srgb, ${color} 44%, #243a28)`,
        filter: `drop-shadow(0 2px 1px rgba(40,55,40,0.22))`,
        opacity: faded ? 0.6 : 1,
      }}
    />
  );
}

function Stack({
  doc,
  x,
  y,
  selected,
  dim,
  onSelect,
}: {
  doc: IngestReport;
  x: number;
  y: number;
  selected: boolean;
  dim: boolean;
  onSelect: () => void;
}) {
  const { plates: ps, overflow } = plates(doc);
  // Height from the base plate up to the top (plus a gap before held plates).
  let heldSeen = false;
  const positioned = ps.map((p, i) => {
    if (p.held && !heldSeen) heldSeen = true;
    const lift = i * STEP + (p.held ? GAP : 0);
    return { ...p, lift };
  });
  const topLift = positioned.at(-1)?.lift ?? 0;
  const stackH = topLift + TH;

  return (
    <button
      onClick={onSelect}
      aria-pressed={selected}
      aria-label={`${doc.title}, ${doc.chunks_indexed} chunks, ${doc.trust_level.toLowerCase()} trust`}
      className="group absolute origin-bottom outline-none transition-[transform,filter] duration-300"
      style={{
        left: x,
        top: y - stackH,
        width: TW,
        height: stackH + 34,
        transform: selected ? "translateY(-10px) scale(1.04)" : undefined,
        filter: dim ? "grayscale(0.5) opacity(0.45)" : undefined,
        zIndex: Math.round(y),
      }}
    >
      {/* ground shadow */}
      <div
        className="absolute"
        style={{
          left: TW * 0.1,
          top: stackH - TH / 2,
          width: TW * 0.8,
          height: TH * 0.8,
          borderRadius: "50%",
          background: "rgba(45,60,45,0.18)",
          filter: "blur(11px)",
        }}
      />
      {selected && (
        <div
          className="absolute animate-pulse"
          style={{
            left: -6,
            top: stackH - TH - 6,
            width: TW + 12,
            height: TH + 12,
            clipPath: "polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)",
            background: "transparent",
            boxShadow: "0 0 0 2px #43714c",
          }}
        />
      )}
      {positioned.map((p, i) => (
        <div key={i} className="absolute left-0" style={{ bottom: p.lift + 34 }}>
          <Diamond color={p.color} faded={p.held} />
        </div>
      ))}
      <div
        className="pointer-events-none absolute left-1/2 -translate-x-1/2 rounded-lg px-2 py-1 text-center backdrop-blur-sm"
        style={{
          top: stackH + 6,
          maxWidth: TW + 48,
          background: selected ? "color-mix(in srgb, var(--brand) 14%, #ffffff)" : "rgba(255,255,255,0.82)",
          boxShadow: selected
            ? "0 2px 8px rgba(40,55,40,0.14), inset 0 0 0 1px color-mix(in srgb, var(--brand) 45%, transparent)"
            : "0 2px 6px rgba(40,55,40,0.1), inset 0 0 0 1px rgba(39,48,41,0.1)",
        }}
      >
        <div
          className={`font-display truncate text-[11px] font-semibold tracking-wide ${
            selected ? "text-ink" : "text-ink-2 group-hover:text-ink"
          }`}
        >
          {doc.title}
        </div>
        <div className="text-[10px] text-muted">
          {doc.chunks_indexed} chunks{overflow ? ` +${overflow}` : ""}
        </div>
      </div>
    </button>
  );
}

export function Landscape({
  documents,
  stats,
  selectedId,
  onSelect,
  chunks,
}: {
  documents: IngestReport[];
  stats?: KbStats;
  selectedId: string | null;
  onSelect: (id: string) => void;
  chunks?: DocumentChunkView[];
}) {
  const docs = useMemo(
    () => [...documents].sort((a, b) => b.chunks_total - a.chunks_total),
    [documents],
  );

  // Isometric grid placement, centered and depth-sorted so nearer stacks paint
  // over farther ones. Spacing (HW/HH) is wider than a plate so stacks read as a
  // spread-out terrain rather than a cramped pile.
  const cols = Math.max(1, Math.round(Math.sqrt(docs.length)));
  const placed = docs.map((doc, i) => {
    const r = Math.floor(i / cols);
    const c = i % cols;
    return { doc, isoX: c - r, isoY: c + r };
  });
  const xs = placed.map((p) => p.isoX);
  const ys = placed.map((p) => p.isoY);
  const minX = Math.min(0, ...xs);
  const maxX = Math.max(0, ...xs);
  const minY = Math.min(0, ...ys);
  const maxY = Math.max(0, ...ys);
  const midX = (minX + maxX) / 2;
  const tallest = docs.length ? Math.max(...docs.map(stackHeight)) : TH;
  const topPad = tallest + 28;
  const canvasW = Math.max(700, (maxX - minX) * HW + TW + 160);
  const canvasH = topPad + (maxY - minY) * HH + 128;
  const groundX = (isoX: number) => canvasW / 2 - TW / 2 + (isoX - midX) * HW;
  const groundY = (isoY: number) => topPad + (isoY - minY) * HH;
  placed.sort((a, b) => a.isoY - b.isoY || a.isoX - b.isoX);

  const held = stats?.chunks_quarantined ?? documents.reduce((s, d) => s + d.chunks_quarantined, 0);
  const eligible = stats?.chunks_indexed ?? documents.reduce((s, d) => s + d.chunks_indexed, 0);
  const screened = stats?.chunks_screened ?? eligible + held;
  const untrusted =
    stats?.source_summaries.filter((x) => x.trust_level === "UNTRUSTED" || x.trust_score < 0.3).length ?? 0;
  const selected = documents.find((d) => d.document_id === selectedId) ?? null;

  return (
    <div className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
      {/* left rail — live totals + document index */}
      <div className="space-y-3">
        <div className="rounded-2xl border border-edge bg-gradient-to-br from-white to-[var(--surface-2)] p-5 shadow-card">
          <div className="eyebrow !text-[color:var(--brand)]">Ready for retrieval</div>
          <div className="font-heading mt-1 flex items-baseline gap-1.5 text-ink">
            <span className="text-4xl font-bold tabular">{formatNumber(eligible)}</span>
            <span className="text-lg text-muted">/ {formatNumber(screened)}</span>
          </div>
          <div className="mt-2 text-xs text-ink-2">Eligible chunks across your archive</div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-2xl border border-edge bg-surface p-4 shadow-card">
            <div className="flex items-center gap-1.5 text-[10px] font-semibold tracking-wider text-ink-2 uppercase">
              <ShieldAlert className="h-3.5 w-3.5 text-[color:var(--critical)]" /> Quarantined
            </div>
            <div className="font-heading mt-1 text-2xl font-bold tabular text-ink">{formatNumber(held)}</div>
          </div>
          <div className="rounded-2xl border border-edge bg-surface p-4 shadow-card">
            <div className="flex items-center gap-1.5 text-[10px] font-semibold tracking-wider text-ink-2 uppercase">
              <Boxes className="h-3.5 w-3.5 text-[color:var(--warning)]" /> Untrusted
            </div>
            <div className="font-heading mt-1 text-2xl font-bold tabular text-ink">{formatNumber(untrusted)}</div>
          </div>
        </div>
        <div className="rounded-2xl border border-edge bg-surface p-2 shadow-card">
          <div className="px-3 py-2 text-[10px] font-semibold tracking-wider text-muted uppercase">
            Documents · {documents.length}
          </div>
          <ul className="max-h-[22rem] space-y-0.5 overflow-auto px-1 pb-1">
            {docs.map((d) => {
              const active = d.document_id === selectedId;
              return (
                <li key={d.document_id}>
                  <button
                    onClick={() => onSelect(d.document_id)}
                    className={`flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left transition ${
                      active ? "bg-[color-mix(in_srgb,var(--brand)_12%,transparent)] ring-1 ring-[color-mix(in_srgb,var(--brand)_35%,transparent)]" : "hover:bg-surface-2"
                    }`}
                  >
                    <span
                      className="h-7 w-7 shrink-0 rounded-md"
                      style={{
                        background: `linear-gradient(135deg, ${TRUST_COLOR[d.trust_level]}, color-mix(in srgb, ${TRUST_COLOR[d.trust_level]} 52%, #243a28))`,
                      }}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-medium text-ink">{d.title}</span>
                      <span className="block truncate text-[11px] text-muted">
                        {d.chunks_indexed} chunks{d.chunks_quarantined ? ` · ${d.chunks_quarantined} held` : ""}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      </div>

      {/* the isometric viewport — a soft, light 3D terrain panel */}
      <div className="overflow-hidden rounded-2xl border border-edge bg-[radial-gradient(900px_500px_at_72%_-10%,rgba(124,166,132,0.22),transparent_60%),linear-gradient(160deg,#f1f6ee,#e6eee1)] shadow-card">
        <div className="flex items-center justify-between px-5 pt-4">
          <div>
            <div className="eyebrow !text-[color:var(--brand)]">Archive terrain</div>
            <div className="font-heading mt-1 text-xl font-semibold text-ink">Your archive. Every layer, visible.</div>
            <div className="mt-1 text-xs text-ink-2">A document is a stack. Each layer is a chunk.</div>
          </div>
          <div className="hidden gap-3 text-[11px] text-ink-2 sm:flex">
            <Legend color="#6f9a5f" label="Indexed" />
            <Legend color={FLAGGED} label="Sanitized" />
            <Legend color={HELD} label="Quarantined" />
          </div>
        </div>
        <div className="overflow-x-auto px-4 pb-6">
          {docs.length ? (
            <div className="relative mx-auto" style={{ width: canvasW, height: canvasH }}>
              {placed.map(({ doc, isoX, isoY }) => (
                <Stack
                  key={doc.document_id}
                  doc={doc}
                  x={groundX(isoX)}
                  y={groundY(isoY)}
                  selected={doc.document_id === selectedId}
                  dim={selectedId !== null && doc.document_id !== selectedId}
                  onSelect={() => onSelect(doc.document_id)}
                />
              ))}
            </div>
          ) : (
            <div className="flex h-56 items-center justify-center text-sm text-ink-2">
              No documents indexed yet — add data to build the landscape.
            </div>
          )}
        </div>

        {/* selected document — real chunk structure */}
        {selected && (
          <div className="grid gap-4 border-t border-edge bg-[rgba(255,255,255,0.55)] px-5 py-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
            <div>
              <div className="text-[10px] font-semibold tracking-wider text-muted uppercase">Selected source</div>
              <div className="font-heading mt-1 text-lg font-semibold text-ink">{selected.title}</div>
              <div className="mt-1 text-xs text-ink-2">
                {selected.source} · trust {selected.trust_level.toLowerCase()}
              </div>
              <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-2">
                <span className="tabular">{selected.chunks_indexed} indexed</span>
                <span className="tabular">{selected.chunks_flagged} sanitized</span>
                <span className="tabular text-[color:var(--critical)]">{selected.chunks_quarantined} quarantined</span>
              </div>
            </div>
            <div>
              <div className="text-[10px] font-semibold tracking-wider text-muted uppercase">
                Document structure · {chunks?.length ?? selected.chunks_indexed} chunks
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(chunks ?? []).map((c) => {
                  const color = c.firewall_action === "FLAG" ? FLAGGED : "#6f9a5f";
                  return (
                    <span
                      key={c.chunk_index}
                      title={`chunk #${c.chunk_index} · ${c.firewall_action.toLowerCase()} · score ${c.firewall_score.toFixed(2)}`}
                      className="font-heading grid h-8 w-8 place-items-center rounded-md text-[11px] font-semibold text-ink tabular"
                      style={{ background: `color-mix(in srgb, ${color} 20%, #ffffff)`, border: `1px solid ${color}` }}
                    >
                      {c.chunk_index + 1}
                    </span>
                  );
                })}
                {!chunks?.length && (
                  <span className="text-xs text-ink-2">Loading chunk structure…</span>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-2.5 w-2.5 rounded-sm" style={{ background: color }} /> {label}
    </span>
  );
}

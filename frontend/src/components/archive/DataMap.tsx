import { Minus, Pause, Play, Plus, RotateCcw, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { ArchiveDocument } from "../../types";
import { Button, formatBytes, formatNumber, inputClass } from "../ui";
import { directDocuments, type TreeNode } from "./tree";

/* A 3D graph of the whole archive: the archive at the centre, sections around it,
   folders around their sections at different heights, and every document as a dot in
   a small 3D cloud around its folder. Circle size is how much data a node holds;
   document colour is its screening status.

   Plain, solid, bright colours (no glow). Drawn on a 2D canvas with a perspective
   projection, in screen pixels every frame, so circles stay crisp at any zoom. One
   animation loop blooms the map in, turns it slowly, glides the camera, keeps a little
   momentum after a drag, and fades highlights and filters. Nearer things are larger and
   brighter. With "reduce motion" set, everything is instant and still. */

type Status = "ready" | "sanitized" | "low" | "blocked";
type SizeBy = "chunks" | "bytes";
type Review = "any" | "approved" | "pending";

const STATUS: Record<Status, { label: string; cssVar: string }> = {
  ready: { label: "Clean", cssVar: "--good" },
  sanitized: { label: "Sanitized", cssVar: "--warning" },
  low: { label: "Untrusted / low trust", cssVar: "--serious" },
  blocked: { label: "Blocked", cssVar: "--critical" },
};
const ALL_STATUSES: Status[] = ["ready", "sanitized", "low", "blocked"];
const STATUS_INDEX: Record<Status, number> = { ready: 0, sanitized: 1, low: 2, blocked: 3 };

const statusOf = (d: ArchiveDocument): Status =>
  d.chunks_quarantined ? "blocked" : !d.retrieval_allowed ? "low" : d.chunks_flagged ? "sanitized" : "ready";

interface MapNode {
  id: string;
  kind: "root" | "section" | "folder" | "document";
  label: string;
  x: number; // world position (y is up)
  y: number;
  z: number;
  r: number;
  path: string[]; // ids of every ancestor, root first
  parent: number; // index of the parent node (-1 for the root)
  delay: number; // ms after the map opens before this node blooms in
  phase: number; // offset of its gentle drift
  tree?: TreeNode;
  doc?: ArchiveDocument;
  status?: Status;
}

const RING = 240; // distance between levels, in map units
const GOLDEN = Math.PI * (3 - Math.sqrt(5));
const BLOOM_MS = 650;
const AUTO_SPIN = 0.0001; // radians per ms: the map always turns slowly (~ one turn a minute)

function measure(docs: ArchiveDocument[], sizeBy: SizeBy): number {
  return docs.reduce((n, d) => n + (sizeBy === "chunks" ? d.chunks_total : d.size_bytes), 0);
}

/** Every group gets an angular wedge (sized by how many documents it holds) and a height;
 *  documents fill a small 3D cloud just outside their folder. */
function layout(root: TreeNode, sizeBy: SizeBy) {
  const nodes: MapNode[] = [];
  const total = Math.max(1, measure(root.documents, sizeBy));
  const biggestDoc = Math.max(1, ...root.documents.map((d) => (sizeBy === "chunks" ? d.chunks_total : d.size_bytes)));
  const groupRadius = (docs: ArchiveDocument[], kind: MapNode["kind"]) =>
    (kind === "root" ? 14 : 7) + 40 * Math.sqrt(measure(docs, sizeBy) / total);
  // Small dots: the biggest document is about 5 units across, the smallest 1.5.
  const docRadius = (d: ArchiveDocument) => 1.5 + 3.4 * Math.sqrt((sizeBy === "chunks" ? d.chunks_total : d.size_bytes) / biggestDoc);
  const cloud = (n: number) => 7 * Math.cbrt(n + 0.5); // radius of a cloud of n documents

  function cluster(docs: ArchiveDocument[], cx: number, cy: number, cz: number, parent: number) {
    const p = nodes[parent];
    docs.forEach((d, i) => {
      // Points spread evenly through a ball: radius by cube root, direction by a golden spiral.
      const rr = 7 * Math.cbrt(i + 0.5);
      const v = 1 - 2 * ((i * 0.6180339887) % 1);
      const ring = Math.sqrt(1 - v * v), th = i * GOLDEN;
      nodes.push({
        id: `doc:${d.document_id}`, kind: "document", label: d.title, doc: d, status: statusOf(d),
        x: cx + rr * ring * Math.cos(th), y: cy + rr * v, z: cz + rr * ring * Math.sin(th), r: docRadius(d),
        path: [...p.path, p.id], parent,
        delay: p.delay + 220 + (i / Math.max(1, docs.length)) * 700,
        phase: (nodes.length * 2.399) % (Math.PI * 2),
      });
    });
  }

  function place(tree: TreeNode, parent: number, depth: number, a0: number, a1: number, radius: number) {
    const angle = (a0 + a1) / 2;
    const index = nodes.length;
    const p = parent >= 0 ? nodes[parent] : null;
    // Each group sits at its own height, so the structure opens up when it turns.
    const lift = depth === 0 ? 0 : (((index * 0.6180339887) % 1) - 0.5) * 1.1;
    nodes.push({
      id: tree.key || "root", kind: tree.kind, label: tree.name, tree,
      x: radius * Math.cos(angle) * Math.cos(lift), y: radius * Math.sin(lift), z: radius * Math.sin(angle) * Math.cos(lift),
      r: groupRadius(tree.documents, tree.kind), path: p ? [...p.path, p.id] : [], parent,
      delay: depth * 160, phase: (index * 1.7) % (Math.PI * 2),
    });
    const node = nodes[index];
    const direct = directDocuments(tree);
    const parts: { weight: number; child?: TreeNode; docs?: ArchiveDocument[] }[] = tree.children.map((c) => ({
      weight: Math.sqrt(c.documents.length) + 0.6,
      child: c,
    }));
    if (direct.length && tree.children.length) parts.push({ weight: Math.sqrt(direct.length) + 0.6, docs: direct });
    if (direct.length && !tree.children.length) {
      // A leaf folder: its documents gather just beyond it, away from the centre.
      const len = Math.hypot(node.x, node.y, node.z) || 1;
      const out = node.r + cloud(direct.length) + 10;
      cluster(direct, node.x + (node.x / len) * out, node.y + (node.y / len) * out, node.z + (node.z / len) * out, index);
    }
    const sum = parts.reduce((n, q) => n + q.weight, 0);
    let a = a0;
    for (const q of parts) {
      const span = ((a1 - a0) * q.weight) / sum;
      if (q.child) place(q.child, index, depth + 1, a, a + span, radius + RING);
      else if (q.docs) {
        const mid = a + span / 2, rr = radius + RING * 0.75;
        cluster(q.docs, rr * Math.cos(mid), node.y, rr * Math.sin(mid), index);
      }
      a += span;
    }
  }
  place(root, -1, 0, -Math.PI, Math.PI, 0);
  const extent = Math.max(RING, ...nodes.map((n) => Math.hypot(n.x, n.y, n.z) + n.r));
  return { nodes, extent };
}

const easeOut = (t: number) => 1 - Math.pow(1 - t, 3);
const easeBack = (t: number) => 1 + 2.2 * Math.pow(t - 1, 3) + 1.2 * Math.pow(t - 1, 2); // a little overshoot
const clamp01 = (t: number) => (t < 0 ? 0 : t > 1 ? 1 : t);
const clampPitch = (p: number) => Math.max(-1.35, Math.min(1.35, p));
const approach = (from: number, to: number, dt: number, tau: number) => from + (to - from) * (1 - Math.exp(-dt / tau));

type View = { k: number; tx: number; ty: number };
type Turn = { yaw: number; pitch: number };

export default function DataMap({
  tree,
  scopeKey,
  onScope,
  onOpenDocument,
}: {
  tree: TreeNode;
  scopeKey: string;
  onScope: (key: string) => void;
  onOpenDocument: (doc: ArchiveDocument) => void;
}) {
  const [sizeBy, setSizeBy] = useState<SizeBy>("chunks");
  const [showDocs, setShowDocs] = useState(true);
  const [find, setFind] = useState("");
  const [statuses, setStatuses] = useState<Set<Status>>(() => new Set(ALL_STATUSES));
  const [review, setReview] = useState<Review>("any");
  const [hover, setHover] = useState<{ node: MapNode; x: number; y: number } | null>(null);
  const reduce = useMemo(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches, []);
  const [autoSpin, setAutoSpin] = useState(!reduce);
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const size = useRef({ w: 800, h: 620 });
  const drag = useRef<{ x: number; y: number; t: number; moved: boolean; mode: "turn" | "pan" } | null>(null);

  // ---- data -------------------------------------------------------------
  const treeRef = useRef(tree);
  treeRef.current = tree;
  // Polling hands us a new tree object every 30 s; only re-lay out when the
  // documents themselves change, so the view (and your zoom) is kept.
  const signature = useMemo(
    () =>
      tree.documents
        .map((d) => `${d.document_id}:${d.chunks_total}:${d.size_bytes}:${statusOf(d)}:${d.reviewed_at ?? ""}:${d.section}/${d.folder}`)
        .join("|"),
    [tree],
  );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const { nodes, extent } = useMemo(() => layout(treeRef.current, sizeBy), [signature, sizeBy]);
  const groups = useMemo(() => nodes.filter((n) => n.kind !== "document"), [nodes]);
  const docs = useMemo(() => nodes.filter((n) => n.kind === "document"), [nodes]);
  const needle = find.trim().toLocaleLowerCase();
  const matches = useMemo(
    () => (needle ? new Set(nodes.filter((n) => n.label.toLocaleLowerCase().includes(needle)).map((n) => n.id)) : null),
    [nodes, needle],
  );
  const shownDocs = useMemo(() => {
    const out = new Set<string>();
    for (const n of docs) {
      const d = n.doc!;
      if (!statuses.has(n.status ?? "ready")) continue;
      if (review === "approved" && !d.reviewed_at) continue;
      if (review === "pending" && (d.reviewed_at || n.status === "ready")) continue;
      out.add(n.id);
    }
    return out;
  }, [docs, statuses, review]);
  const filtering = statuses.size < ALL_STATUSES.length || review !== "any";
  const shownTotals = useMemo(() => {
    let chunks = 0, bytes = 0;
    for (const n of docs) if (shownDocs.has(n.id)) { chunks += n.doc!.chunks_total; bytes += n.doc!.size_bytes; }
    return { chunks, bytes };
  }, [docs, shownDocs]);
  const groupsWithShown = useMemo(() => {
    const out = new Set<string>();
    for (const n of docs) if (shownDocs.has(n.id)) for (const id of n.path) out.add(id);
    return out;
  }, [docs, shownDocs]);
  const reviewCounts = useMemo(() => {
    let approved = 0, pending = 0;
    for (const d of tree.documents) {
      if (d.reviewed_at) approved += 1;
      else if (statusOf(d) !== "ready") pending += 1;
    }
    return { approved, pending };
  }, [tree]);
  const totals = useMemo(() => {
    const t = { chunks: 0, bytes: 0, ready: 0, sanitized: 0, low: 0, blocked: 0 };
    for (const d of tree.documents) {
      t.chunks += d.chunks_total;
      t.bytes += d.size_bytes;
      t[statusOf(d)] += 1;
    }
    return t;
  }, [tree]);
  const toggleStatus = (st: Status) =>
    setStatuses((prev) => {
      const next = new Set(prev);
      if (next.has(st) && next.size > 1) next.delete(st);
      else next.add(st);
      return next;
    });

  // ---- animation engine (refs: the loop never waits for React) ------------
  const view = useRef<View>({ k: 1, tx: 0, ty: 0 }); // zoom and screen offset, as drawn
  const target = useRef<View>({ k: 1, tx: 0, ty: 0 }); // where they are heading
  const turn = useRef<Turn>({ yaw: 0.3, pitch: 0.42 }); // camera orbit, as drawn
  const turnTarget = useRef<Turn>({ yaw: 0.3, pitch: 0.42 });
  const panVelocity = useRef({ x: 0, y: 0 }); // drag momentum, px per ms
  const spinVelocity = useRef({ yaw: 0, pitch: 0 }); // turn momentum, rad per ms
  const lastTouch = useRef(0); // the last time someone moved the map by hand
  const anim = useRef({
    alpha: new Float32Array(0), scale: new Float32Array(0),
    px: new Float32Array(0), py: new Float32Array(0), pz: new Float32Array(0), // animated world position
    sx: new Float32Array(0), sy: new Float32Array(0), sr: new Float32Array(0), sd: new Float32Array(0), // projected
    order: new Int32Array(0),
  });
  const born = useRef(0);
  const visible = useRef(true);
  const running = useRef(false);
  const lastFrame = useRef(0);
  // Theme colours, read from CSS once (reading styles every frame is slow).
  const palette = useRef<{ fills: string[]; page: string; ink: string; ink2: string } | null>(null);
  const fitted = useRef(false);

  // Everything the loop reads from React, refreshed every render.
  const live = useRef({ nodes, extent, showDocs, shownDocs, groupsWithShown, filtering, matches, hover: hover?.node ?? null, scopeKey, autoSpin });
  live.current = { nodes, extent, showDocs, shownDocs, groupsWithShown, filtering, matches, hover: hover?.node ?? null, scopeKey, autoSpin };

  // A fresh layout blooms in from the centre.
  useEffect(() => {
    const n = nodes.length;
    anim.current = {
      alpha: new Float32Array(n), scale: new Float32Array(n),
      px: new Float32Array(n), py: new Float32Array(n), pz: new Float32Array(n),
      sx: new Float32Array(n), sy: new Float32Array(n), sr: new Float32Array(n), sd: new Float32Array(n),
      order: Int32Array.from({ length: n }, (_, i) => i),
    };
    born.current = reduce ? -1e9 : performance.now();
    kick();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes]);

  const frame = useCallback((now: number) => {
    const c = canvas.current;
    const ctx = c?.getContext("2d");
    if (!c || !ctx) { running.current = false; return; }
    const dt = Math.min(64, now - (lastFrame.current || now)) || 16;
    lastFrame.current = now;
    const L = live.current;
    const A = anim.current;
    const N = L.nodes;
    if (A.alpha.length !== N.length) { running.current = false; return; }

    // Camera: coast after a drag, turn slowly when idle, glide towards targets.
    const v = view.current, T = target.current, pv = panVelocity.current;
    const R = turn.current, RT = turnTarget.current, sv = spinVelocity.current;
    let busy = false;
    if (!drag.current) {
      if (Math.abs(pv.x) + Math.abs(pv.y) > 0.003) {
        T.tx += pv.x * dt; T.ty += pv.y * dt; v.tx += pv.x * dt; v.ty += pv.y * dt;
        const decay = Math.exp(-dt / 260);
        pv.x *= decay; pv.y *= decay; busy = true;
      } else { pv.x = 0; pv.y = 0; }
      if (Math.abs(sv.yaw) + Math.abs(sv.pitch) > 0.00002) {
        RT.yaw += sv.yaw * dt; RT.pitch = clampPitch(RT.pitch + sv.pitch * dt);
        R.yaw += sv.yaw * dt; R.pitch = clampPitch(R.pitch + sv.pitch * dt);
        const decay = Math.exp(-dt / 600);
        sv.yaw *= decay; sv.pitch *= decay; busy = true;
      } else { sv.yaw = 0; sv.pitch = 0; }
      if (L.autoSpin && !reduce && visible.current && now - lastTouch.current > 1000) {
        RT.yaw += AUTO_SPIN * dt;
        busy = true;
      }
    }
    const tau = reduce ? 0.0001 : 140;
    v.k = approach(v.k, T.k, dt, tau);
    v.tx = approach(v.tx, T.tx, dt, tau);
    v.ty = approach(v.ty, T.ty, dt, tau);
    R.yaw = approach(R.yaw, RT.yaw, dt, reduce ? 0.0001 : 160);
    R.pitch = approach(R.pitch, RT.pitch, dt, reduce ? 0.0001 : 160);
    if (Math.abs(v.k - T.k) / T.k > 0.0005 || Math.abs(v.tx - T.tx) > 0.15 || Math.abs(v.ty - T.ty) > 0.15) busy = true;
    if (Math.abs(R.yaw - RT.yaw) > 0.0005 || Math.abs(R.pitch - RT.pitch) > 0.0005) busy = true;

    // Which nodes are highlighted, kept by the filters, hovered.
    const focus = L.hover ?? (L.scopeKey ? N.find((n) => n.id === L.scopeKey) : undefined);
    const lit = (n: MapNode) => {
      if (L.matches) return L.matches.has(n.id) || n.path.some((p) => L.matches!.has(p));
      if (!focus || focus.kind === "root") return true;
      return n.id === focus.id || n.path.includes(focus.id) || focus.path.includes(n.id);
    };
    const since = now - born.current;
    const fadeTau = reduce ? 0.0001 : 180;
    const drift = !reduce && visible.current;

    // Per node: bloom-in, fade and resize towards targets, drift, then project to the screen.
    const cy = Math.cos(R.yaw), syw = Math.sin(R.yaw), cp = Math.cos(R.pitch), sp = Math.sin(R.pitch);
    const D = L.extent * 2.4; // camera distance: enough perspective to read as depth, not distort
    for (let i = 0; i < N.length; i++) {
      const n = N[i];
      const isDoc = n.kind === "document";
      const shown = isDoc ? L.showDocs && L.shownDocs.has(n.id) : !L.filtering || n.kind === "root" || L.groupsWithShown.has(n.id);
      const on = lit(n);
      const aTarget = !shown ? (isDoc ? 0 : 0.14) : on ? 1 : isDoc ? 0.1 : 0.18;
      const sTarget = !shown && isDoc ? 0 : L.hover === n ? (isDoc ? 1.8 : 1.1) : 1;
      A.alpha[i] = approach(A.alpha[i], aTarget, dt, fadeTau);
      A.scale[i] = approach(A.scale[i], sTarget, dt, fadeTau * 0.8);
      if (Math.abs(A.alpha[i] - aTarget) > 0.004 || Math.abs(A.scale[i] - sTarget) > 0.004) busy = true;

      const p = clamp01((since - n.delay) / BLOOM_MS);
      if (p < 1) busy = true;
      const e = isDoc ? easeOut(p) : easeBack(p);
      const ox = n.parent >= 0 ? A.px[n.parent] : 0, oy = n.parent >= 0 ? A.py[n.parent] : 0, oz = n.parent >= 0 ? A.pz[n.parent] : 0;
      const amp = drift ? (isDoc ? 1.1 : n.kind === "root" ? 0 : 2.5) * p : 0;
      const wx = ox + (n.x - ox) * e + amp * Math.sin(now * 0.00055 + n.phase);
      const wy = oy + (n.y - oy) * e + amp * Math.cos(now * 0.00047 + n.phase * 1.3);
      const wz = oz + (n.z - oz) * e + amp * Math.sin(now * 0.0005 + n.phase * 0.7);
      A.px[i] = wx; A.py[i] = wy; A.pz[i] = wz;

      // Orbit (yaw around the vertical axis, then pitch), then perspective.
      const x1 = wx * cy + wz * syw, z1 = -wx * syw + wz * cy;
      const y2 = wy * cp - z1 * sp, z2 = wy * sp + z1 * cp;
      const persp = D / (D + z2);
      A.sx[i] = v.tx + v.k * x1 * persp;
      A.sy[i] = v.ty - v.k * y2 * persp;
      A.sr[i] = n.r * A.scale[i] * v.k * persp;
      A.sd[i] = z2;
    }
    // Far things first, so nearer ones cover them.
    A.order.sort((a, b) => A.sd[b] - A.sd[a]);

    // Paint every frame the display offers (60, 120, 144 Hz…): the frame is cheap enough.
    paint(ctx, lit, now);
    if (busy || drift) requestAnimationFrame(frame);
    else running.current = false;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reduce]);

  /** Everything is drawn in screen pixels, so circles and lines stay crisp at any zoom.
   *  Kept cheap so it can run at the display's full frame rate: colours are cached, the
   *  thousands of document links go out as a handful of paths, and dots are drawn one
   *  colour at a time (changing the fill colour per dot is what costs the most). */
  function paint(ctx: CanvasRenderingContext2D, lit: (n: MapNode) => boolean, now: number) {
    if (!palette.current) {
      const css = getComputedStyle(document.documentElement);
      const c = (name: string) => css.getPropertyValue(name).trim() || "#999";
      palette.current = {
        fills: [c("--good"), c("--warning"), c("--serious"), c("--critical")],
        page: c("--page"), ink: c("--ink"), ink2: c("--ink-2"),
      };
    }
    const P = palette.current;
    const dpr = window.devicePixelRatio || 1;
    const { w, h } = size.current;
    const { k } = view.current;
    const L = live.current, A = anim.current, N = L.nodes;
    const since = now - born.current;
    const ext = L.extent;
    // Depth cue: near = full colour, the far side of the map fades to about 40%.
    const fogScale = 1 / (2 * ext * 0.9);
    const fog = (z: number) => 0.4 + 0.6 * clamp01(0.5 - z * fogScale);
    const bloom = (i: number) => clamp01((since - N[i].delay) / BLOOM_MS);

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.lineCap = "round";

    // Links. Folder links one by one (few); document links grouped by brightness into a
    // handful of paths, each stroked once.
    const BUCKETS = 8;
    const docLinks: Path2D[] = Array.from({ length: BUCKETS + 1 }, () => new Path2D());
    let anyDocLink = false;
    for (let i = 0; i < N.length; i++) {
      const n = N[i];
      if (n.parent < 0) continue;
      const a = Math.min(A.alpha[i], A.alpha[n.parent] + 0.3) * bloom(i) * fog(A.sd[i]);
      if (a < 0.01) continue;
      const x0 = A.sx[n.parent], y0 = A.sy[n.parent], x1 = A.sx[i], y1 = A.sy[i];
      const mx = (x0 + x1) / 2, my = (y0 + y1) / 2, bend = i % 2 ? 0.1 : -0.1;
      const qx = mx - (y1 - y0) * bend, qy = my + (x1 - x0) * bend;
      if (n.kind === "document") {
        const path = docLinks[Math.max(1, Math.round(a * BUCKETS))];
        path.moveTo(x0, y0);
        path.quadraticCurveTo(qx, qy, x1, y1);
        anyDocLink = true;
      } else {
        ctx.strokeStyle = `rgba(200,200,200,${0.5 * a})`;
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.moveTo(x0, y0);
        ctx.quadraticCurveTo(qx, qy, x1, y1);
        ctx.stroke();
      }
    }
    if (anyDocLink) {
      ctx.lineWidth = 0.6;
      ctx.strokeStyle = "rgb(170,170,170)";
      for (let b = 1; b <= BUCKETS; b++) {
        ctx.globalAlpha = (0.16 * b) / BUCKETS;
        ctx.stroke(docLinks[b]);
      }
      ctx.globalAlpha = 1;
    }

    // Documents, far to near within each colour: plain solid dots, with a fine dark edge
    // once they are big enough, so neighbours stay distinct when you zoom in.
    if (L.showDocs) {
      const order = A.order;
      for (let s = 0; s < 4; s++) {
        ctx.fillStyle = P.fills[s];
        ctx.strokeStyle = P.page;
        ctx.lineWidth = 1;
        for (let j = 0; j < order.length; j++) {
          const i = order[j];
          const n = N[i];
          if (n.kind !== "document" || STATUS_INDEX[n.status ?? "ready"] !== s) continue;
          const a = A.alpha[i] * bloom(i) * fog(A.sd[i]);
          const r = A.sr[i];
          if (a < 0.01 || r < 0.15) continue;
          ctx.globalAlpha = a;
          ctx.beginPath();
          ctx.arc(A.sx[i], A.sy[i], r < 0.7 ? 0.7 : r, 0, Math.PI * 2);
          ctx.fill();
          if (r > 3) ctx.stroke();
        }
      }
      ctx.globalAlpha = 1;
    }

    // Groups, far to near: flat solid circles; the selected or hovered one gets a ring.
    for (const i of A.order) {
      const n = N[i];
      if (n.kind === "document") continue;
      const a = A.alpha[i] * clamp01((since - n.delay) / (BLOOM_MS * 0.6)) * fog(A.sd[i]);
      if (a < 0.01) continue;
      const r = Math.max(2, A.sr[i]);
      const x = A.sx[i], y = A.sy[i];
      ctx.globalAlpha = a;
      ctx.fillStyle = n.kind === "root" ? "#f2f2f2" : n.kind === "section" ? "#cfcfcf" : "#a3a3a3";
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = P.page;
      ctx.stroke();
      if (n.id === L.scopeKey || L.hover === n) {
        ctx.lineWidth = 2;
        ctx.strokeStyle = P.ink;
        ctx.beginPath();
        ctx.arc(x, y, r + 5, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;

    // Labels: groups always (dimmer at the back); document names fade in as you get close.
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const ink = P.ink, ink2 = P.ink2;
    let font = "";
    for (const i of A.order) {
      const n = N[i];
      const doc = n.kind === "document";
      if (doc && (!L.showDocs || k < 1.6)) continue;
      let a = A.alpha[i] * clamp01((since - n.delay - 200) / BLOOM_MS) * fog(A.sd[i]);
      if (doc) a *= clamp01((A.sr[i] - 3) / 3) * clamp01((k - 1.6) / 1.2);
      if (!doc && !lit(n) && n.kind !== "section") a *= 0.4;
      if (a < 0.03) continue;
      ctx.globalAlpha = Math.min(1, a);
      const fontPx = n.kind === "root" ? 14 : n.kind === "section" ? 13 : n.kind === "folder" ? 11.5 : 10;
      const want = `${doc ? 400 : 600} ${fontPx}px "Inter Variable", system-ui, sans-serif`;
      if (want !== font) { ctx.font = want; font = want; }
      ctx.fillStyle = doc ? ink2 : ink;
      const text = n.label.length > 28 ? n.label.slice(0, 27) + "…" : n.label;
      ctx.fillText(text, A.sx[i], A.sy[i] + Math.max(2, A.sr[i]) + 4);
    }
    ctx.globalAlpha = 1;
  }

  const kick = useCallback(() => {
    if (running.current) return;
    running.current = true;
    lastFrame.current = 0;
    requestAnimationFrame(frame);
  }, [frame]);

  // Anything React changes (hover, filters, find, focus) just restarts the loop.
  useEffect(() => kick());

  // ---- camera --------------------------------------------------------------
  const fitView = useCallback((): View => {
    const { w, h } = size.current;
    return { k: Math.min(w, h) / (2 * extent * 1.02), tx: w / 2, ty: h / 2 };
  }, [extent]);
  const fitRef = useRef(fitView);
  fitRef.current = fitView;

  useEffect(() => {
    const el = wrap.current, c = canvas.current;
    if (!el || !c) return;
    const resize = () => {
      const w = el.clientWidth, h = el.clientHeight, dpr = window.devicePixelRatio || 1;
      const prev = size.current;
      size.current = { w, h };
      c.width = Math.round(w * dpr);
      c.height = Math.round(h * dpr);
      c.style.width = `${w}px`;
      c.style.height = `${h}px`;
      if (!fitted.current) {
        // First open: start a little zoomed out, then settle in as the map blooms.
        const f = fitRef.current();
        view.current = reduce ? { ...f } : { ...f, k: f.k * 0.7 };
        target.current = { ...f };
        fitted.current = true;
      } else {
        const sx = (w - prev.w) / 2, sy = (h - prev.h) / 2;
        view.current = { ...view.current, tx: view.current.tx + sx, ty: view.current.ty + sy };
        target.current = { ...target.current, tx: target.current.tx + sx, ty: target.current.ty + sy };
      }
      kick();
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    // Animate only while the map is on screen and the tab is visible.
    const io = new IntersectionObserver(([entry]) => { visible.current = entry.isIntersecting && !document.hidden; if (visible.current) kick(); });
    io.observe(el);
    const onVisibility = () => { visible.current = !document.hidden; if (visible.current) kick(); };
    document.addEventListener("visibilitychange", onVisibility);
    return () => { ro.disconnect(); io.disconnect(); document.removeEventListener("visibilitychange", onVisibility); };
  }, [kick, reduce]);

  function local(clientX: number, clientY: number) {
    const rect = canvas.current!.getBoundingClientRect();
    return { sx: clientX - rect.left, sy: clientY - rect.top };
  }
  function zoomBy(factor: number, sx = size.current.w / 2, sy = size.current.h / 2) {
    const T = target.current;
    const k = Math.min(60, Math.max(0.05, T.k * factor));
    target.current = { k, tx: sx - ((sx - T.tx) * k) / T.k, ty: sy - ((sy - T.ty) * k) / T.k };
    panVelocity.current = { x: 0, y: 0 };
    kick();
  }
  /** Fly to a group: zoom so the group and everything under it fills the view (it keeps turning). */
  function focusOn(n: MapNode) {
    spinVelocity.current = { yaw: 0, pitch: 0 };
    panVelocity.current = { x: 0, y: 0 };
    const { yaw, pitch } = turnTarget.current;
    const cy = Math.cos(yaw), syw = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
    const D = extent * 2.4;
    const pts = nodes.filter((m) => m.id === n.id || m.path.includes(n.id)).map((m) => {
      const x1 = m.x * cy + m.z * syw, z1 = -m.x * syw + m.z * cy;
      const y2 = m.y * cp - z1 * sp, z2 = m.y * sp + z1 * cp;
      const p = D / (D + z2);
      return { x: x1 * p, y: -y2 * p, r: m.r * p };
    });
    const x0 = Math.min(...pts.map((p) => p.x - p.r)), x1 = Math.max(...pts.map((p) => p.x + p.r));
    const y0 = Math.min(...pts.map((p) => p.y - p.r)), y1 = Math.max(...pts.map((p) => p.y + p.r));
    const { w, h } = size.current;
    const k = Math.min(30, 0.82 * Math.min(w / (x1 - x0 + 40), h / (y1 - y0 + 40)));
    target.current = { k, tx: w / 2 - ((x0 + x1) / 2) * k, ty: h / 2 - ((y0 + y1) / 2) * k };
    kick();
  }
  function resetView() {
    target.current = fitView();
    turnTarget.current = { yaw: turnTarget.current.yaw, pitch: 0.42 };
    panVelocity.current = { x: 0, y: 0 };
    spinVelocity.current = { yaw: 0, pitch: 0 };
    setAutoSpin(!reduce);
    onScope("");
    kick();
  }

  // Wheel zoom needs a non-passive listener, or the page scrolls along with the map.
  const wheelRef = useRef<(e: WheelEvent) => void>(() => {});
  wheelRef.current = (e: WheelEvent) => {
    e.preventDefault();
    const p = local(e.clientX, e.clientY);
    zoomBy(Math.exp(-e.deltaY * 0.0015), p.sx, p.sy);
  };
  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const onWheel = (e: WheelEvent) => wheelRef.current(e);
    c.addEventListener("wheel", onWheel, { passive: false });
    return () => c.removeEventListener("wheel", onWheel);
  }, []);

  // Picking a folder in the structure tree flies the map to it too.
  const focusRef = useRef(focusOn);
  focusRef.current = focusOn;
  useEffect(() => {
    const goal = scopeKey ? groups.find((n) => n.id === scopeKey) : undefined;
    if (goal) focusRef.current(goal);
  }, [scopeKey, groups]);

  /** Hit-test on the projected screen positions; the nearest thing under the pointer wins. */
  function hit(sx: number, sy: number): MapNode | null {
    const A = anim.current;
    if (A.alpha.length !== nodes.length) return null;
    let best: MapNode | null = null, bestDepth = Infinity, bestIsGroup = false;
    for (let i = 0; i < nodes.length; i++) {
      const n = nodes[i];
      const isDoc = n.kind === "document";
      if (isDoc && (!showDocs || !shownDocs.has(n.id))) continue;
      if (A.alpha[i] < 0.05) continue;
      const r = Math.max(isDoc ? 3 : 5, A.sr[i]) + 3;
      if (Math.hypot(A.sx[i] - sx, A.sy[i] - sy) > r) continue;
      // Groups are drawn above documents, so they win; otherwise the nearest one does.
      if ((!isDoc && !bestIsGroup) || (isDoc === !bestIsGroup && A.sd[i] < bestDepth)) {
        best = n; bestDepth = A.sd[i]; bestIsGroup = !isDoc;
      }
    }
    return best;
  }

  const hovered = hover?.node;
  const groupDocs = hovered?.tree?.documents ?? [];
  const mix = hovered?.tree
    ? ALL_STATUSES.map((s) => [s, groupDocs.filter((d) => statusOf(d) === s).length] as const)
    : [];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <label className="relative min-w-[200px] flex-1">
          <span className="sr-only">Find in the map</span>
          <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted" />
          <input className={`${inputClass} pl-9`} placeholder="Find a document, folder or section…" value={find} onChange={(e) => setFind(e.target.value)} />
        </label>
        <div className="shrink-0">
          <label className="sr-only" htmlFor="map-size">Circle size</label>
          <select id="map-size" className={`${inputClass} py-2 pr-8`} value={sizeBy} onChange={(e) => setSizeBy(e.target.value as SizeBy)}>
            <option value="chunks">Size: chunks</option>
            <option value="bytes">Size: file size</option>
          </select>
        </div>
        <label className="flex shrink-0 items-center gap-2 text-sm text-ink-2">
          <input type="checkbox" className="h-4 w-4" style={{ accentColor: "var(--brand)" }} checked={showDocs} onChange={(e) => setShowDocs(e.target.checked)} />
          Show documents
        </label>
        <div className="flex shrink-0 gap-1">
          {!reduce && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => { setAutoSpin((s) => !s); lastTouch.current = 0; kick(); }}
              aria-label={autoSpin ? "Stop turning" : "Turn slowly"}
              aria-pressed={autoSpin}
              title={autoSpin ? "Stop turning" : "Turn slowly"}
            >
              {autoSpin ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={() => zoomBy(1 / 1.5)} aria-label="Zoom out"><Minus className="h-4 w-4" /></Button>
          <Button variant="ghost" size="sm" onClick={() => zoomBy(1.5)} aria-label="Zoom in"><Plus className="h-4 w-4" /></Button>
          <Button variant="ghost" size="sm" onClick={resetView} aria-label="Reset view"><RotateCcw className="h-4 w-4" /></Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
        <span className="font-medium text-ink-2">Screening:</span>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Show documents by screening status">
          {ALL_STATUSES.map((st) => {
            const on = statuses.has(st);
            return (
              <button
                key={st}
                aria-pressed={on}
                onClick={() => toggleStatus(st)}
                title={on && statuses.size === 1 ? "At least one status stays selected" : undefined}
                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium transition ${on ? "border-ink-2 bg-surface-2 text-ink" : "border-edge text-muted line-through decoration-1 hover:text-ink-2"}`}
              >
                <span className="h-2 w-2 rounded-full transition-opacity" style={{ background: `var(${STATUS[st].cssVar})`, opacity: on ? 1 : 0.35 }} aria-hidden />
                {STATUS[st].label}
                <span className="tabular text-muted">{formatNumber(totals[st])}</span>
              </button>
            );
          })}
        </div>
        <span className="font-medium text-ink-2">Review:</span>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Show documents by review">
          {([
            ["any", "Any", undefined],
            ["approved", "Approved", reviewCounts.approved],
            ["pending", "Awaiting review", reviewCounts.pending],
          ] as const).map(([id, label, count]) => (
            <button
              key={id}
              aria-pressed={review === id}
              onClick={() => setReview(id)}
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium transition ${review === id ? "border-ink-2 bg-surface-2 text-ink" : "border-edge text-ink-2 hover:text-ink"}`}
            >
              {label}
              {count !== undefined && <span className="tabular text-muted">{formatNumber(count)}</span>}
            </button>
          ))}
        </div>
        {filtering && (
          <button className="text-ink-2 underline hover:text-ink" onClick={() => { setStatuses(new Set(ALL_STATUSES)); setReview("any"); }}>
            Clear filters
          </button>
        )}
      </div>

      <div ref={wrap} className="relative h-[620px] overflow-hidden rounded-xl border border-edge bg-page">
        <canvas
          ref={canvas}
          role="img"
          aria-label={`3D map of the archive: ${formatNumber(tree.documents.length)} documents in ${formatNumber(tree.children.length)} sections, ${formatNumber(totals.chunks)} chunks. The structure tree and the Documents tab list the same data.`}
          className={hovered ? "cursor-pointer" : "cursor-grab active:cursor-grabbing"}
          onContextMenu={(e) => e.preventDefault()}
          onPointerDown={(e) => {
            drag.current = { x: e.clientX, y: e.clientY, t: performance.now(), moved: false, mode: e.shiftKey || e.button === 2 ? "pan" : "turn" };
            panVelocity.current = { x: 0, y: 0 };
            spinVelocity.current = { yaw: 0, pitch: 0 };
            (e.target as HTMLElement).setPointerCapture(e.pointerId);
          }}
          onPointerMove={(e) => {
            const d = drag.current;
            if (d) {
              const dx = e.clientX - d.x, dy = e.clientY - d.y;
              if (Math.abs(dx) + Math.abs(dy) > 2) d.moved = true;
              if (d.moved) {
                const now = performance.now(), dt = Math.max(1, now - d.t);
                lastTouch.current = now;
                if (d.mode === "pan") {
                  view.current = { ...view.current, tx: view.current.tx + dx, ty: view.current.ty + dy };
                  target.current = { ...target.current, tx: target.current.tx + dx, ty: target.current.ty + dy };
                  panVelocity.current = { x: 0.7 * panVelocity.current.x + 0.3 * (dx / dt), y: 0.7 * panVelocity.current.y + 0.3 * (dy / dt) };
                } else {
                  // Drag left/right turns the map around; up/down tilts it.
                  const dyaw = dx * 0.006, dpitch = -dy * 0.006;
                  turn.current = { yaw: turn.current.yaw + dyaw, pitch: clampPitch(turn.current.pitch + dpitch) };
                  turnTarget.current = { yaw: turnTarget.current.yaw + dyaw, pitch: clampPitch(turnTarget.current.pitch + dpitch) };
                  spinVelocity.current = {
                    yaw: 0.7 * spinVelocity.current.yaw + 0.3 * (dyaw / dt),
                    pitch: 0.7 * spinVelocity.current.pitch + 0.3 * (dpitch / dt),
                  };
                }
                d.x = e.clientX; d.y = e.clientY; d.t = now;
                if (hover) setHover(null);
                kick();
                return;
              }
            }
            const p = local(e.clientX, e.clientY);
            const n = hit(p.sx, p.sy);
            if (n !== hover?.node || n) setHover(n ? { node: n, x: p.sx, y: p.sy } : null);
          }}
          onPointerUp={() => {
            const d = drag.current;
            drag.current = null;
            if (d?.moved) {
              // A pause before letting go means "stop here": no coasting.
              if (reduce || performance.now() - d.t > 80) {
                panVelocity.current = { x: 0, y: 0 };
                spinVelocity.current = { yaw: 0, pitch: 0 };
              }
              kick();
              return;
            }
            if (!hovered) return;
            if (hovered.kind === "document" && hovered.doc) onOpenDocument(hovered.doc);
            else { onScope(hovered.kind === "root" ? "" : hovered.id); focusOn(hovered); }
          }}
          onPointerLeave={() => { if (!drag.current) setHover(null); }}
        />
        {hovered && (
          <div
            className="pointer-events-none absolute z-10 w-64 rounded-lg border border-edge bg-surface/95 p-3 text-xs shadow-xl backdrop-blur motion-safe:animate-[fade-in_.15s_ease-out]"
            style={{ left: Math.min(hover!.x + 14, size.current.w - 270), top: Math.min(hover!.y + 14, size.current.h - 150) }}
          >
            <div className="truncate text-sm font-semibold text-ink">{hovered.label}</div>
            <div className="mb-2 text-muted capitalize">{hovered.kind === "root" ? "Whole archive" : hovered.kind}</div>
            {hovered.doc ? (
              <>
                <div className="tabular text-ink-2">{formatNumber(hovered.doc.chunks_total)} chunks · {formatBytes(hovered.doc.size_bytes)}</div>
                <div className="mt-1 flex items-center gap-1.5 text-ink-2">
                  <span className="h-2 w-2 rounded-full" style={{ background: `var(${STATUS[hovered.status ?? "ready"].cssVar})` }} />
                  {STATUS[hovered.status ?? "ready"].label}
                  {hovered.doc.chunks_quarantined > 0 && ` · ${hovered.doc.chunks_quarantined} blocked`}
                </div>
                <div className="mt-1 truncate text-muted">{hovered.doc.section} / {hovered.doc.folder}</div>
                <div className="mt-2 text-muted">Click to open its chunks</div>
              </>
            ) : (
              <>
                <div className="tabular text-ink-2">
                  {formatNumber(groupDocs.length)} documents · {formatNumber(measure(groupDocs, "chunks"))} chunks · {formatBytes(measure(groupDocs, "bytes"))}
                </div>
                <div className="mt-2 flex h-1.5 gap-0.5 overflow-hidden rounded-full">
                  {mix.filter(([, n]) => n > 0).map(([s, n]) => (
                    <span key={s} style={{ flexGrow: n, minWidth: 3, background: `var(${STATUS[s].cssVar})` }} />
                  ))}
                </div>
                <div className="mt-1.5 grid grid-cols-2 gap-x-2 text-muted">
                  {mix.map(([s, n]) => <span key={s} className="tabular">{STATUS[s].label}: {formatNumber(n)}</span>)}
                </div>
                <div className="mt-2 text-muted">Click to focus{hovered.kind !== "root" ? " and list it" : ""}</div>
              </>
            )}
          </div>
        )}
        <div className="pointer-events-none absolute top-3 left-3 rounded-lg bg-surface/80 px-3 py-2 text-xs text-ink-2 backdrop-blur">
          {filtering ? (
            <><span className="tabular font-semibold text-ink">{formatNumber(shownDocs.size)}</span> of {formatNumber(tree.documents.length)} documents shown ·{" "}</>
          ) : (
            <><span className="tabular font-semibold text-ink">{formatNumber(tree.documents.length)}</span> documents ·{" "}</>
          )}
          <span className="tabular font-semibold text-ink">{formatNumber(filtering ? shownTotals.chunks : totals.chunks)}</span> chunks ·{" "}
          <span className="tabular font-semibold text-ink">{formatBytes(filtering ? shownTotals.bytes : totals.bytes)}</span>
          {matches && <> · <span className="tabular font-semibold text-ink">{formatNumber(matches.size)}</span> match “{find.trim()}”</>}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-ink-2">
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-[#a3a3a3]" />Section / folder</span>
        <span className="ml-auto text-muted">
          Circle size = {sizeBy === "chunks" ? "number of chunks" : "file size"} · drag to turn · Shift+drag or right-drag to move · scroll to zoom
        </span>
      </div>
    </div>
  );
}

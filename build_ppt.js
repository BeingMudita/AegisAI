// AegisAI — 8-slide Project Synopsis Presentation
const pptxgen = require("pptxgenjs");
const fs = require("fs");

const pres = new pptxgen();
pres.layout = "LAYOUT_4x3"; // 10 x 7.5 in, matches template
pres.author = "AegisAI Project";
pres.title = "AegisAI — Project Synopsis Presentation";

// ---------- palette ----------
const C = {
  maroon: "9B1B30", red2: "C0504D",
  navy: "1F3864", blue: "2E5496", lblue: "DCE6F5", llblue: "EEF3FB",
  teal: "126E82", lteal: "D5EBEE",
  purple: "5B2C82", lpurple: "E7DDF2",
  green: "2E7D32", lgreen: "D8EAD3",
  amber: "B8860B", lamber: "FCEFCB",
  red: "B71C1C", lred: "F6D5D2",
  grey: "595959", mgrey: "A6A6A6", lgrey: "F0F0F0", line: "BFBFBF",
  white: "FFFFFF", ink: "222222", dark: "1A1A2E",
};
const F = "Calibri";

// ---------- helpers ----------
function slideBase() {
  const s = pres.addSlide();
  s.background = { color: C.white };
  return s;
}
// section header: maroon number chip + navy title
function header(s, num, title) {
  s.addShape(pres.ShapeType.roundRect, { x: 0.5, y: 0.42, w: 0.62, h: 0.62, fill: { color: C.maroon }, line: { type: "none" }, rectRadius: 0.08 });
  s.addText(num, { x: 0.5, y: 0.42, w: 0.62, h: 0.62, align: "center", valign: "middle", fontFace: F, fontSize: 22, bold: true, color: C.white, isTextBox: true, margin: 0 });
  s.addText(title, { x: 1.28, y: 0.4, w: 8.2, h: 0.66, align: "left", valign: "middle", fontFace: F, fontSize: 26, bold: true, color: C.navy, isTextBox: true, margin: 0 });
}
function caption(s, x, y, w, text) {
  s.addText(text, { x, y, w, h: 0.28, align: "center", fontFace: F, fontSize: 10, italic: true, bold: true, color: C.grey, isTextBox: true, margin: 0 });
}
// a node box (rounded) with title + optional sub
function node(s, x, y, w, h, title, sub, fill, line, tc, opts = {}) {
  s.addShape(pres.ShapeType.roundRect, { x, y, w, h, fill: { color: fill }, line: { color: line, width: 1.25 }, rectRadius: opts.radius ?? 0.05 });
  const runs = [{ text: title, options: { bold: true, fontSize: opts.size ?? 12, color: tc, breakLine: !!sub } }];
  if (sub) runs.push({ text: sub, options: { fontSize: opts.subSize ?? 9, color: tc, italic: true } });
  s.addText(runs, { x, y, w, h, align: "center", valign: "middle", fontFace: F, margin: 2, isTextBox: true, lineSpacingMultiple: 0.9 });
}
function vArrow(s, cx, y, len, color) {
  s.addShape(pres.ShapeType.line, { x: cx, y, w: 0, h: len, line: { color: color ?? C.blue, width: 1.75, endArrowType: "triangle" } });
}
function hArrow(s, x, cy, len, color) {
  s.addShape(pres.ShapeType.line, { x, y: cy, w: len, h: 0, line: { color: color ?? C.grey, width: 1.75, endArrowType: "triangle" } });
}
function chip(s, x, y, w, h, label, fill, tc, size) {
  s.addShape(pres.ShapeType.roundRect, { x, y, w, h, fill: { color: fill }, line: { type: "none" }, rectRadius: 0.06 });
  s.addText(label, { x, y, w, h, align: "center", valign: "middle", fontFace: F, fontSize: size ?? 10.5, bold: true, color: tc, isTextBox: true, margin: 1 });
}

// ==========================================================
// SLIDE 1 — TITLE (matches template format)
// ==========================================================
(function () {
  const s = slideBase();
  s.addImage({ path: "logo_dronacharya.jpeg", x: 3.0, y: 0.6, w: 4.0, h: 0.878 });
  s.addText("DEPARTMENT OF CSE", { x: 0.5, y: 1.62, w: 9, h: 0.5, align: "center", fontFace: F, fontSize: 22, bold: true, color: C.red2, isTextBox: true, charSpacing: 1 });
  s.addText("Project Synopsis Presentation", { x: 0.5, y: 2.45, w: 9, h: 0.45, align: "center", fontFace: F, fontSize: 18, color: C.grey, isTextBox: true });
  s.addText("AegisAI", { x: 0.5, y: 2.85, w: 9, h: 1.0, align: "center", fontFace: F, fontSize: 60, bold: true, color: C.dark, isTextBox: true });
  s.addText("A Trust-Aware Security Gateway for RAG-Powered Agentic AI", { x: 0.75, y: 3.95, w: 8.5, h: 0.55, align: "center", fontFace: F, fontSize: 19, bold: true, color: C.navy, isTextBox: true });
  s.addText("“Trust the knowledge.  Control the action.”", { x: 0.5, y: 4.55, w: 9, h: 0.4, align: "center", fontFace: F, fontSize: 14, italic: true, color: C.teal, isTextBox: true });
  const sub = [
    { text: "Submitted by:", options: { bold: true, breakLine: true } },
    { text: "Name:", options: { breakLine: true } },
    { text: "Roll No:", options: { breakLine: true } },
    { text: "Branch:", options: { breakLine: true } },
    { text: "Semester:", options: { breakLine: true } },
    { text: "Batch: 2022-2026", options: {} },
  ];
  s.addText(sub, { x: 5.3, y: 5.55, w: 4.2, h: 1.6, align: "right", fontFace: F, fontSize: 13, bold: true, color: C.grey, isTextBox: true, lineSpacingMultiple: 1.1 });
  s.addNotes("Title slide. AegisAI is a security middleware for RAG-powered AI agents. Introduce the guiding principle: trust the knowledge, control the action.");
})();

// ==========================================================
// SLIDE 2 — CONTENTS (agenda as 2x2 numbered cards)
// ==========================================================
(function () {
  const s = slideBase();
  s.addText("Contents", { x: 0.5, y: 0.35, w: 9, h: 0.7, align: "center", fontFace: F, fontSize: 34, bold: true, color: C.navy, isTextBox: true });
  const cards = [
    ["1", "Introduction of Project", ["Problem statement & motivation", "Objectives  •  System architecture"], C.lblue, C.blue, "Slides 3 – 4"],
    ["2", "Technology Used", ["Backend, AI/LLM & RAG stack", "Database, frontend & DevOps"], C.lteal, C.teal, "Slide 5"],
    ["3", "Flowchart, Methodology & Snapshots", ["Request-handling flowchart", "SOC-style security dashboard"], C.lpurple, C.purple, "Slides 6 – 7"],
    ["4", "Timeline & Conclusion", ["Gantt / PERT project plan", "Expected outcomes & summary"], C.lamber, C.amber, "Slide 8"],
  ];
  const W = 4.35, H = 2.35, gx = 0.55, gy = 0.3;
  const xs = [0.5, 0.5 + W + gx], ys = [1.35, 1.35 + H + gy];
  cards.forEach((c, i) => {
    const x = xs[i % 2], y = ys[Math.floor(i / 2)];
    s.addShape(pres.ShapeType.roundRect, { x, y, w: W, h: H, fill: { color: C.white }, line: { color: C.line, width: 1 }, rectRadius: 0.08, shadow: { type: "outer", color: "BFBFBF", blur: 5, offset: 2, angle: 90, opacity: 0.5 } });
    s.addShape(pres.ShapeType.ellipse, { x: x + 0.28, y: y + 0.28, w: 0.7, h: 0.7, fill: { color: c[4] } });
    s.addText(c[0], { x: x + 0.28, y: y + 0.28, w: 0.7, h: 0.7, align: "center", valign: "middle", fontFace: F, fontSize: 26, bold: true, color: C.white, isTextBox: true, margin: 0 });
    s.addText(c[1], { x: x + 1.15, y: y + 0.28, w: W - 1.35, h: 0.9, align: "left", valign: "middle", fontFace: F, fontSize: 15.5, bold: true, color: C.navy, isTextBox: true, margin: 0 });
    const bl = c[2].map((t, k) => ({ text: t, options: { bullet: { code: "2022" }, breakLine: k < c[2].length - 1, fontSize: 12, color: C.ink } }));
    s.addText(bl, { x: x + 0.32, y: y + 1.2, w: W - 0.6, h: 0.72, align: "left", fontFace: F, isTextBox: true, paraSpaceAfter: 4 });
    s.addText(c[5], { x: x + 0.32, y: y + H - 0.42, w: W - 0.6, h: 0.32, align: "left", fontFace: F, fontSize: 10.5, italic: true, bold: true, color: c[3], isTextBox: true, margin: 0 });
  });
  s.addNotes("Agenda: four parts following the required chapter format — Introduction, Technology, Flowchart/Methodology/Snapshots, and Timeline/Conclusion.");
})();

// ==========================================================
// SLIDE 3 — 1. Introduction & Objectives
// ==========================================================
(function () {
  const s = slideBase();
  header(s, "1", "Introduction & Objectives");
  // left: concept diagram (two boundaries)
  s.addText("The core problem", { x: 0.5, y: 1.25, w: 4.3, h: 0.35, fontFace: F, fontSize: 15, bold: true, color: C.maroon, isTextBox: true, margin: 0 });
  s.addText([
    { text: "AI agents retrieve external knowledge and ", options: {} },
    { text: "act", options: { bold: true, italic: true } },
    { text: " on it through tools. A poisoned document can hide instructions that trigger an ", options: {} },
    { text: "unsafe action", options: { bold: true } },
    { text: " (e.g. data exfiltration).", options: {} },
  ], { x: 0.5, y: 1.6, w: 4.3, h: 1.0, fontFace: F, fontSize: 12.5, color: C.ink, isTextBox: true, lineSpacingMultiple: 1.0, align: "left" });
  // two-boundary vertical diagram
  const dx = 0.7, dw = 3.9;
  node(s, dx, 2.75, dw, 0.62, "RAG TRUST LAYER", "“Can I trust this information?”", C.lteal, C.teal, C.navy, { size: 12.5, subSize: 9.5 });
  vArrow(s, dx + dw / 2, 3.42, 0.34, C.teal);
  node(s, dx, 3.82, dw, 0.6, "AI AGENT", "reason  •  plan  •  propose action", C.lblue, C.blue, C.navy, { size: 12.5, subSize: 9.5 });
  vArrow(s, dx + dw / 2, 4.47, 0.34, C.purple);
  node(s, dx, 4.87, dw, 0.62, "ACTION SECURITY FIREWALL", "“Should this action be allowed?”", C.lpurple, C.purple, C.navy, { size: 12.5, subSize: 9.5 });
  caption(s, dx, 5.55, dw, "Fig 1.1 — Two independent security boundaries");
  s.addText([{ text: "Even if one layer misses an attack, the other still stops the action — ", options: {} }, { text: "defense in depth.", options: { bold: true, color: C.maroon } }], { x: dx - 0.15, y: 5.88, w: dw + 0.3, h: 0.7, fontFace: F, fontSize: 11.5, color: C.ink, isTextBox: true, align: "center", lineSpacingMultiple: 0.95 });

  // right: 6 objective chips (2 x 3)
  s.addText("Objectives", { x: 5.15, y: 1.25, w: 4.35, h: 0.35, fontFace: F, fontSize: 15, bold: true, color: C.maroon, isTextBox: true, margin: 0 });
  const objs = [
    ["O1", "Secure RAG inputs", C.lteal, C.teal],
    ["O2", "Contextual trust score", C.lteal, C.teal],
    ["O3", "Intercept agent actions", C.lpurple, C.purple],
    ["O4", "Enforce authorization", C.lpurple, C.purple],
    ["O5", "Monitor data-flow", C.lamber, C.amber],
    ["O6", "Provide audit evidence", C.lamber, C.amber],
  ];
  const ow = 4.35, oh = 0.78, oy0 = 1.65, ogy = 0.16;
  objs.forEach((o, i) => {
    const y = oy0 + i * (oh + ogy);
    s.addShape(pres.ShapeType.roundRect, { x: 5.15, y, w: ow, h: oh, fill: { color: o[2] }, line: { color: o[3], width: 1 }, rectRadius: 0.06 });
    s.addShape(pres.ShapeType.ellipse, { x: 5.32, y: y + 0.14, w: 0.5, h: 0.5, fill: { color: o[3] } });
    s.addText(o[0], { x: 5.32, y: y + 0.14, w: 0.5, h: 0.5, align: "center", valign: "middle", fontFace: F, fontSize: 12, bold: true, color: C.white, isTextBox: true, margin: 0 });
    s.addText(o[1], { x: 5.95, y, w: ow - 0.95, h: oh, align: "left", valign: "middle", fontFace: F, fontSize: 13.5, bold: true, color: C.navy, isTextBox: true, margin: 0 });
  });
  s.addNotes("Problem: indirect prompt injection can turn retrieved knowledge into malicious actions. AegisAI answers two questions with two boundaries. Six objectives span securing inputs, trust scoring, action interception, authorization, data-flow monitoring, and auditing.");
})();

// ==========================================================
// SLIDE 4 — 1. System Architecture (hero diagram)
// ==========================================================
(function () {
  const s = slideBase();
  header(s, "1", "System Architecture");
  const CX = 5.0;
  const full = { x: 2.15, w: 5.7 };
  let y = 1.28;
  const gap = 0.16, bh = 0.5;
  // USER
  node(s, full.x, y, full.w, 0.42, "USER  —  “Summarize invoices & flag issues”", null, C.lgrey, C.mgrey, C.navy, { size: 11 });
  y += 0.42 + gap; vArrow(s, CX, y - gap, gap, C.grey);
  node(s, full.x, y, full.w, bh, "TASK & POLICY ENGINE", "intent • permissions • destinations", C.lblue, C.blue, C.navy, { size: 11.5, subSize: 8.5 });
  y += bh + gap; vArrow(s, CX, y - gap, gap, C.grey);
  // two columns: knowledge | policy
  node(s, 2.15, y, 2.78, bh, "KNOWLEDGE LAYER", "docs • web • PDF • email • DB", C.lteal, C.teal, C.navy, { size: 10.5, subSize: 8 });
  node(s, 5.07, y, 2.78, bh, "POLICY STORE", "agent/tool/data policies", C.lpurple, C.purple, C.navy, { size: 10.5, subSize: 8 });
  y += bh + gap; vArrow(s, CX, y - gap, gap, C.grey);
  // RAG TRUST GATEWAY
  node(s, full.x, y, full.w, 0.6, "RAG TRUST GATEWAY", "Provenance | Instruction | Semantic  ➔  Trust Engine   →   TRUSTED / SUSPICIOUS / BLOCK", C.lteal, C.teal, C.navy, { size: 11.5, subSize: 8.5 });
  y += 0.6 + gap; vArrow(s, CX, y - gap, gap, C.teal);
  node(s, full.x, y, full.w, bh, "AI AGENT", "LLM + RAG • reasoning • planning  ➔  tool proposal", C.lblue, C.blue, C.navy, { size: 11.5, subSize: 8.5 });
  y += bh + gap; vArrow(s, CX, y - gap, gap, C.purple);
  node(s, full.x, y, full.w, 0.6, "AGENT SECURITY FIREWALL", "Tool Auth | Parameter | Data-Flow  ➔  Risk Engine   →   ALLOW / CONFIRM / BLOCK", C.lpurple, C.purple, C.navy, { size: 11.5, subSize: 8.5 });
  y += 0.6 + gap; vArrow(s, CX, y - gap, gap, C.grey);
  // three outputs
  node(s, 2.15, y, 1.8, 0.42, "TOOLS / APIs", null, C.lgrey, C.mgrey, C.navy, { size: 10 });
  node(s, 4.1, y, 1.8, 0.42, "SECURITY AUDIT", null, C.lamber, C.amber, C.navy, { size: 10 });
  node(s, 6.05, y, 1.8, 0.42, "SOC DASHBOARD", null, C.lgreen, C.green, C.navy, { size: 10 });
  caption(s, 2.15, y + 0.48, full.w, "Fig 1.2 — End-to-end architecture: trust the knowledge, then control the action");
  s.addNotes("Seven cooperating layers. Knowledge is trust-assessed before the agent sees it; every proposed action is authorized by the firewall before any tool runs; all decisions stream to audit and the dashboard.");
})();

// ==========================================================
// SLIDE 5 — 2. Technology Used (layered stack)
// ==========================================================
(function () {
  const s = slideBase();
  header(s, "2", "Technology Used");
  const rows = [
    ["Presentation", ["React", "TypeScript", "Tailwind", "Recharts / ECharts"], C.lgreen, C.green],
    ["Security Middleware", ["FastAPI", "JWT Auth", "Interception", "Firewall Engine"], C.lpurple, C.purple],
    ["Agent & AI", ["LangGraph", "OpenAI / Ollama", "Sentence-Transformers"], C.lblue, C.blue],
    ["Knowledge / RAG", ["LlamaIndex", "Custom RAG pipeline"], C.lteal, C.teal],
    ["Data", ["PostgreSQL", "pgvector", "Redis (optional)"], C.lamber, C.amber],
    ["Platform", ["Docker", "Docker Compose", "Git / GitHub"], C.lgrey, C.grey],
  ];
  const x = 0.5, w = 9.0, y0 = 1.35, rh = 0.82, rgy = 0.09;
  const labelW = 2.5;
  rows.forEach((r, i) => {
    const y = y0 + i * (rh + rgy);
    // label block
    s.addShape(pres.ShapeType.roundRect, { x, y, w: labelW, h: rh, fill: { color: C.navy }, line: { type: "none" }, rectRadius: 0.05 });
    s.addText(r[0], { x: x + 0.05, y, w: labelW - 0.1, h: rh, align: "center", valign: "middle", fontFace: F, fontSize: 13, bold: true, color: C.white, isTextBox: true, margin: 0 });
    // tech chips
    const chips = r[1];
    const cxStart = x + labelW + 0.18;
    const cAreaW = w - labelW - 0.18;
    const cW = Math.min(1.75, (cAreaW - (chips.length - 1) * 0.12) / chips.length);
    const totalW = chips.length * cW + (chips.length - 1) * 0.12;
    let cx = cxStart;
    chips.forEach((t) => {
      chip(s, cx, y + 0.14, cW, rh - 0.28, t, r[2], r[3], 11);
      cx += cW + 0.12;
    });
  });
  caption(s, 0.5, y0 + rows.length * (rh + rgy) + 0.02, 9.0, "Fig 2.1 — Layered technology stack (core: Python · FastAPI · PostgreSQL/pgvector · React)");
  s.addNotes("A controlled, modern stack. Core is Python + FastAPI + PostgreSQL/pgvector + one LLM + React. Redis and extra vector DBs added only if required.");
})();

// ==========================================================
// SLIDE 6 — 3. Flowchart & Methodology
// ==========================================================
(function () {
  const s = slideBase();
  header(s, "3", "Flowchart & Methodology");
  // LEFT: request-handling flowchart
  const lx = 0.55, lw = 4.5, cx = lx + lw / 2;
  let y = 1.3;
  const bh = 0.4, g = 0.14;
  node(s, lx + 0.9, y, lw - 1.8, bh, "User Request", null, C.lgrey, C.mgrey, C.navy, { size: 10.5 });
  y += bh + g; vArrow(s, cx, y - g, g, C.grey);
  node(s, lx + 0.6, y, lw - 1.2, bh, "Task & Policy Engine", null, C.lblue, C.blue, C.navy, { size: 10.5 });
  y += bh + g; vArrow(s, cx, y - g, g, C.grey);
  node(s, lx + 0.6, y, lw - 1.2, bh, "RAG Retrieval", null, C.lteal, C.teal, C.navy, { size: 10.5 });
  y += bh + g; vArrow(s, cx, y - g, g, C.grey);
  node(s, lx, y, lw, 0.44, "◆ Trust Assessment", null, C.lamber, C.amber, "6B4E00", { size: 10.5 });
  y += 0.44 + g; vArrow(s, cx, y - g, g, C.blue);
  // 3-way trust branch
  const tw = (lw - 0.24) / 3;
  chip(s, lx, y, tw, 0.42, "TRUSTED", C.lgreen, C.green, 9.5);
  chip(s, lx + tw + 0.12, y, tw, 0.42, "SUSPICIOUS", C.lamber, "6B4E00", 9);
  chip(s, lx + 2 * (tw + 0.12), y, tw, 0.42, "UNTRUSTED", C.lred, C.red, 9);
  y += 0.42 + g; vArrow(s, cx, y - g, g, C.grey);
  node(s, lx + 0.5, y, lw - 1.0, bh, "AI Agent  →  tool proposal", null, C.lblue, C.blue, C.navy, { size: 10.5 });
  y += bh + g; vArrow(s, cx, y - g, g, C.purple);
  node(s, lx, y, lw, 0.44, "◆ Agent Security Firewall", null, C.lamber, C.amber, "6B4E00", { size: 10.5 });
  y += 0.44 + g; vArrow(s, cx, y - g, g, C.blue);
  chip(s, lx, y, tw, 0.42, "🟢 ALLOW", C.lgreen, C.green, 9.5);
  chip(s, lx + tw + 0.12, y, tw, 0.42, "🟡 CONFIRM", C.lamber, "6B4E00", 9);
  chip(s, lx + 2 * (tw + 0.12), y, tw, 0.42, "🔴 BLOCK", C.lred, C.red, 9.5);
  caption(s, lx, y + 0.46, lw, "Fig 3.1 — Request-handling flowchart");

  // RIGHT: three-decision model + trust score
  const rx = 5.4, rw = 4.15;
  s.addText("Three-decision model", { x: rx, y: 1.3, w: rw, h: 0.35, fontFace: F, fontSize: 14, bold: true, color: C.maroon, isTextBox: true, margin: 0 });
  const dec = [
    ["🟢  ALLOW", "Complies with policy — tool runs.", C.lgreen, C.green],
    ["🟡  CONFIRM", "Possibly legitimate — needs user approval.", C.lamber, "6B4E00"],
    ["🔴  BLOCK", "Outside authorization — rejected & logged.", C.lred, C.red],
  ];
  let dy = 1.7;
  dec.forEach((d) => {
    s.addShape(pres.ShapeType.roundRect, { x: rx, y: dy, w: rw, h: 0.72, fill: { color: d[2] }, line: { color: d[3], width: 1.25 }, rectRadius: 0.06 });
    s.addText([{ text: d[0] + "   ", options: { bold: true, fontSize: 13, color: d[3] } }, { text: d[1], options: { fontSize: 10.5, color: C.ink } }], { x: rx + 0.15, y: dy, w: rw - 0.3, h: 0.72, align: "left", valign: "middle", fontFace: F, isTextBox: true, margin: 2, lineSpacingMultiple: 0.9 });
    dy += 0.72 + 0.16;
  });
  s.addText("Trust score (deterministic, explainable)", { x: rx, y: dy + 0.05, w: rw, h: 0.35, fontFace: F, fontSize: 14, bold: true, color: C.maroon, isTextBox: true, margin: 0 });
  const sig = ["Provenance", "Instruction detection", "Task relevance", "Policy consistency", "Security history"];
  const bl = sig.map((t, k) => ({ text: t + "  ", options: { bullet: { code: "2022" }, breakLine: true, fontSize: 11.5, color: C.ink } }));
  bl.push({ text: "= 0–100  →  TRUSTED / SUSPICIOUS / UNTRUSTED", options: { bold: true, fontSize: 11.5, color: C.navy } });
  s.addText(bl, { x: rx + 0.05, y: dy + 0.42, w: rw, h: 1.9, align: "left", fontFace: F, isTextBox: true, paraSpaceAfter: 3 });
  s.addNotes("The flowchart shows two independent decision points. Trust is scored from five interpretable signals; the firewall issues one of three auditable decisions.");
})();

// ==========================================================
// SLIDE 7 — 3. Snapshots — SOC Dashboard
// ==========================================================
(function () {
  const s = slideBase();
  header(s, "3", "Snapshots — SOC-Style Dashboard");
  // KPI tiles
  const kpis = [
    ["04", "Active Agents", C.lblue], ["238", "Docs Scanned", C.lteal], ["17", "Suspicious", C.lamber],
    ["31", "Blocked", C.lred], ["09", "Confirms", C.lgreen], ["05", "High-Risk", C.lpurple],
  ];
  const kw = 1.44, kh = 0.95, kx0 = 0.5, ky = 1.3, kg = 0.1;
  kpis.forEach((k, i) => {
    const x = kx0 + i * (kw + kg);
    s.addShape(pres.ShapeType.roundRect, { x, y: ky, w: kw, h: kh, fill: { color: k[2] }, line: { color: C.line, width: 0.75 }, rectRadius: 0.06 });
    s.addText(k[0], { x, y: ky + 0.06, w: kw, h: 0.5, align: "center", fontFace: F, fontSize: 26, bold: true, color: C.navy, isTextBox: true, margin: 0 });
    s.addText(k[1], { x, y: ky + 0.58, w: kw, h: 0.32, align: "center", fontFace: F, fontSize: 9.5, color: C.grey, isTextBox: true, margin: 0 });
  });
  // activity feed (dark terminal)
  s.addText("Agent Activity — FinanceAgent", { x: 0.5, y: 2.5, w: 5.0, h: 0.3, fontFace: F, fontSize: 13, bold: true, color: C.navy, isTextBox: true, margin: 0 });
  s.addShape(pres.ShapeType.roundRect, { x: 0.5, y: 2.85, w: 5.6, h: 2.3, fill: { color: "1E1E1E" }, line: { type: "none" }, rectRadius: 0.04 });
  const feed = [
    ["12:41:02  ", "Retrieved invoice_42.pdf", "9CDCFE"],
    ["12:41:02  ", "⚠ Suspicious instruction detected", "DCDCAA"],
    ["12:41:03  ", "Trust → LOW (SUSPICIOUS)", "DCDCAA"],
    ["12:41:04  ", "Proposed  send_email()", "9CDCFE"],
    ["12:41:04  ", "⚠ Sensitive data: customers.csv", "DCDCAA"],
    ["12:41:04  ", "🔴 ACTION BLOCKED", "F48771"],
  ];
  const feedRuns = [];
  feed.forEach((f, i) => {
    feedRuns.push({ text: f[0], options: { color: "6A9955", fontSize: 11.5, fontFace: "Consolas" } });
    feedRuns.push({ text: f[1], options: { color: f[2], fontSize: 11.5, fontFace: "Consolas", breakLine: true } });
  });
  s.addText(feedRuns, { x: 0.7, y: 2.98, w: 5.3, h: 2.05, align: "left", valign: "top", isTextBox: true, margin: 0, lineSpacingMultiple: 1.15 });

  // attack graph (right)
  s.addText("Attack Graph (reconstructed)", { x: 6.35, y: 2.5, w: 3.15, h: 0.3, fontFace: F, fontSize: 13, bold: true, color: C.navy, isTextBox: true, margin: 0 });
  const ax = 6.35, aw = 3.15;
  const ag = [
    ["Malicious Document", C.lred, C.red], ["Prompt Injection", C.lred, C.red],
    ["Agent Reasoning", C.lblue, C.blue], ["Sensitive File", C.lamber, C.amber],
    ["External API", C.lamber, C.amber], ["🔴 BLOCKED", C.lred, C.red],
  ];
  let ay = 2.9; const abh = 0.34, ag2 = 0.1;
  ag.forEach((n, i) => {
    node(s, ax, ay, aw, abh, n[0], null, n[1], n[2], (n[2] === C.red ? "6B1414" : C.navy), { size: 10 });
    ay += abh;
    if (i < ag.length - 1) { vArrow(s, ax + aw / 2, ay, ag2, C.grey); ay += ag2; }
  });
  caption(s, 0.5, 5.72, 9.0, "Fig 3.3 — SOC dashboard: overview KPIs, live agent feed and reconstructed attack chain");
  s.addNotes("The dashboard is the primary demo surface — a mini SOC for AI agents. It shows a poisoned invoice being detected and the resulting exfiltration attempt blocked, fully reconstructed as an attack graph.");
})();

// ==========================================================
// SLIDE 8 — 4. Timeline & Conclusion
// ==========================================================
(function () {
  const s = slideBase();
  header(s, "4", "Timeline & Conclusion");
  // Gantt-style bar chart (native)
  s.addText("4-Month Development Plan (16 weeks)", { x: 0.5, y: 1.2, w: 9, h: 0.32, fontFace: F, fontSize: 14, bold: true, color: C.maroon, isTextBox: true, margin: 0 });
  // Build a stacked horizontal bar (offset + duration) to emulate a Gantt
  const tasks = ["M1 · Foundation & Agent", "M2 · RAG Trust Layer", "M3 · Agent Firewall", "M4 · Dashboard, Eval & Docs"];
  const offset = [0, 4, 8, 12];
  const dur = [4, 4, 4, 4];
  const chartData = [
    { name: "offset", labels: tasks, values: offset },
    { name: "Duration (weeks)", labels: tasks, values: dur },
  ];
  s.addChart(pres.ChartType.bar, chartData, {
    x: 0.5, y: 1.55, w: 5.7, h: 2.7,
    barDir: "bar", barGrouping: "stacked",
    chartColors: ["FFFFFF", C.blue],
    chartColorsOpacity: [0, 100],
    showLegend: false, showTitle: false,
    catAxisLabelColor: C.ink, catAxisLabelFontSize: 10, catAxisLabelFontFace: F,
    valAxisLabelColor: C.grey, valAxisLabelFontSize: 9,
    valAxisMinVal: 0, valAxisMaxVal: 16, valAxisMajorUnit: 4,
    valGridLine: { color: "E0E0E0", size: 0.75 }, catGridLine: { style: "none" },
    valAxisTitle: "Weeks", showValAxisTitle: true, valAxisTitleColor: C.grey, valAxisTitleFontSize: 9,
    barGapWidthPct: 60,
  });
  caption(s, 0.5, 4.3, 5.7, "Fig 4.1 — Gantt chart of the development plan");

  // PERT mini (right)
  s.addText("Critical path", { x: 6.5, y: 1.2, w: 3.0, h: 0.32, fontFace: F, fontSize: 14, bold: true, color: C.maroon, isTextBox: true, margin: 0 });
  const pnodes = [["A · Foundation", C.lblue, C.blue], ["B · Trust Layer", C.lteal, C.teal], ["C · Firewall", C.lpurple, C.purple], ["D · Eval & Docs", C.lgreen, C.green]];
  let py = 1.6; const pbh = 0.5, pg = 0.16;
  pnodes.forEach((n, i) => {
    node(s, 6.5, py, 3.0, pbh, n[0], "4 weeks", n[1], n[2], C.navy, { size: 11, subSize: 8.5 });
    py += pbh;
    if (i < pnodes.length - 1) { vArrow(s, 8.0, py, pg, C.grey); py += pg; }
  });
  caption(s, 6.5, py + 0.05, 3.0, "Fig 4.2 — PERT (A→B→C→D = 16 wks)");

  // Conclusion band
  s.addShape(pres.ShapeType.roundRect, { x: 0.5, y: 4.85, w: 9.0, h: 1.9, fill: { color: C.navy }, line: { type: "none" }, rectRadius: 0.06 });
  s.addText("Conclusion", { x: 0.75, y: 4.98, w: 8.5, h: 0.35, fontFace: F, fontSize: 15, bold: true, color: "9CC3FF", isTextBox: true, margin: 0 });
  s.addText([
    { text: "AegisAI unites a ", options: {} },
    { text: "RAG Trust Layer", options: { bold: true, color: "8FD6E1" } },
    { text: " and an ", options: {} },
    { text: "Agent Security Firewall", options: { bold: true, color: "C9B6E6" } },
    { text: ", linked by trust propagation, into one buildable defense-in-depth system for agentic AI.", options: {} },
  ], { x: 0.75, y: 5.35, w: 8.5, h: 0.8, fontFace: F, fontSize: 13.5, color: "F0F0F0", isTextBox: true, align: "left", lineSpacingMultiple: 1.0 });
  s.addText("“Trust the knowledge.  Control the action.”", { x: 0.75, y: 6.15, w: 8.5, h: 0.45, fontFace: F, fontSize: 17, bold: true, italic: true, color: "FFFFFF", isTextBox: true, align: "center" });
  s.addNotes("The plan is milestone-driven over four months on a single critical path. Conclusion: combining knowledge-level trust with action-level authorization gives defense in depth — trust the knowledge, control the action.");
})();

pres.writeFile({ fileName: "AegisAI_Presentation.pptx" }).then((f) => console.log("WROTE", f));

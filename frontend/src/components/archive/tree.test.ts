import { describe, expect, it } from "vitest";
import type { ArchiveDocument } from "../../types";
import { buildTree, countFolders, directDocuments, docNodeKey, findNode, matchesQuery, nodeKey, pathTo, sortDocuments } from "./tree";

const doc = (patch: Partial<ArchiveDocument> = {}): ArchiveDocument => ({
  document_id: "doc-1", title: "Memo", section: "Finance", folder: "General", source: "Ledger",
  chunks_total: 10, chunks_indexed: 8, chunks_flagged: 2, chunks_quarantined: 2,
  trust_level: "HIGH", source_trust: .8, retrieval_allowed: true, retrieval_reason: null,
  source_type: "FILE", filename: null, size_bytes: 2000, created_at: "2026-10-08T10:00:00Z", ...patch,
});

describe("database tree", () => {
  const docs = [
    doc({ document_id: "a", folder: "Invoices/2026" }),
    doc({ document_id: "b", folder: "Invoices/2025" }),
    doc({ document_id: "c", folder: "Invoices" }),
    doc({ document_id: "d", section: "HR", folder: "General" }),
  ];

  it("nests folder paths and counts every document below a node", () => {
    const root = buildTree(docs);
    expect(root.children.map(s => s.name)).toEqual(["Finance", "HR"]);
    const invoices = findNode(root, nodeKey("Finance", "Invoices"))!;
    expect(invoices.documents.map(d => d.document_id)).toEqual(["a", "b", "c"]);
    expect(invoices.children.map(c => c.name)).toEqual(["2025", "2026"]);
    expect(countFolders(root)).toBe(4); // Invoices, 2025, 2026, General
    expect(pathTo(root, nodeKey("Finance", "Invoices/2026")).map(n => n.name)).toEqual(["All documents", "Finance", "Invoices", "2026"]);
    expect(pathTo(root, "missing")).toEqual([root]);
    expect(findNode(root, docNodeKey(docs[0]))!.name).toBe("2026");
    // "c" sits in Invoices itself; "a" and "b" are in its subfolders.
    expect(directDocuments(invoices).map(d => d.document_id)).toEqual(["c"]);
    expect(directDocuments(findNode(root, nodeKey("Finance", "Invoices/2026"))!).map(d => d.document_id)).toEqual(["a"]);
    expect(directDocuments(root)).toEqual([]);
  });

  it("files documents without a location under Unsorted / General", () => {
    const root = buildTree([doc({ document_id: "z", section: "", folder: "" })]);
    expect(findNode(root, nodeKey("Unsorted", "General"))!.documents.map(d => d.document_id)).toEqual(["z"]);
  });

  it("keeps a section named with a slash apart from a folder", () => {
    const root = buildTree([doc({ document_id: "x", section: "A/B" }), doc({ document_id: "y", section: "A", folder: "B" })]);
    expect(findNode(root, nodeKey("A/B"))!.documents.map(d => d.document_id)).toEqual(["x"]);
    expect(findNode(root, nodeKey("A", "B"))!.documents.map(d => d.document_id)).toEqual(["y"]);
  });

  it("sorts numbers numerically, names naturally, and breaks ties by name", () => {
    const rows = [
      doc({ document_id: "1", title: "File 10", size_bytes: 50 }),
      doc({ document_id: "2", title: "File 9", size_bytes: 900 }),
      doc({ document_id: "3", title: "File 2", size_bytes: 50 }),
    ];
    expect(sortDocuments(rows, "title", "asc").map(d => d.title)).toEqual(["File 2", "File 9", "File 10"]);
    expect(sortDocuments(rows, "size", "desc").map(d => d.title)).toEqual(["File 9", "File 2", "File 10"]);
  });

  it("searches name, file, source and location", () => {
    expect(matchesQuery(doc({ filename: "Finance/bill.pdf" }), "BILL")).toBe(true);
    expect(matchesQuery(doc({ folder: "Invoices/2026" }), "2026")).toBe(true);
    expect(matchesQuery(doc(), "payroll")).toBe(false);
  });
});

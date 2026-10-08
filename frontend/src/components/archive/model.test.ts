import { describe, expect, it } from "vitest";
import type { ArchiveDocument } from "../../types";
import { countArchive } from "./model";

const document = (patch: Partial<ArchiveDocument> = {}): ArchiveDocument => ({
  document_id: "doc-1", title: "Memo", section: "Finance", folder: "Invoices", source: "Ledger",
  chunks_total: 10, chunks_indexed: 8, chunks_flagged: 2, chunks_quarantined: 2,
  trust_level: "HIGH", source_trust: .8, retrieval_allowed: true, retrieval_reason: null,
  source_type: "FILE", filename: null, size_bytes: 2000, created_at: "2026-10-08", ...patch,
});

describe("archive projection", () => {
  it("keeps low trust and sanitized counts disjoint", () => {
    expect(countArchive([document(), document({ retrieval_allowed: false })])).toEqual({
      docs: 2, chunks: 20, eligible: 8, ready: 6, sanitized: 2, blocked: 4, low: 8,
    });
  });
});

import type { ArchiveDocument, ArchiveStatus } from "../../types";

export const statusLabels: Record<ArchiveStatus, string> = {
  ready: "Ready", sanitized: "Sanitized", low: "Low trust", blocked: "Blocked",
};
export function countArchive(documents: ArchiveDocument[]) {
  const counts = { docs: documents.length, chunks: 0, ready: 0, sanitized: 0, blocked: 0, low: 0, eligible: 0 };
  for (const doc of documents) {
    counts.chunks += doc.chunks_total;
    counts.blocked += doc.chunks_quarantined;
    if (!doc.retrieval_allowed) counts.low += doc.chunks_indexed;
    else {
      counts.sanitized += doc.chunks_flagged;
      counts.ready += Math.max(0, doc.chunks_indexed - doc.chunks_flagged);
      counts.eligible += doc.chunks_indexed;
    }
  }
  return counts;
}

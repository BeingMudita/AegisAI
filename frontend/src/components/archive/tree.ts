import type { ArchiveDocument } from "../../types";

/** One node of the database tree: the whole database, a section, or a folder path inside one. */
export interface TreeNode {
  key: string; // "" = the whole database
  name: string;
  kind: "root" | "section" | "folder";
  section: string;
  path: string; // folder path inside the section ("" for the section itself)
  documents: ArchiveDocument[]; // everything at or below this node
  children: TreeNode[];
}

export type SortKey = "title" | "location" | "source" | "trust" | "chunks" | "quarantined" | "size" | "created";
export type SortDir = "asc" | "desc";

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

/** JSON keeps "A/B" + "" distinct from "A" + "B". */
export const nodeKey = (section: string, path = "") => JSON.stringify([section, path]);

const folderParts = (doc: ArchiveDocument) => (doc.folder || "General").split("/").filter(Boolean);

/** The tree node of the folder a document sits in. */
export const docNodeKey = (doc: ArchiveDocument) => nodeKey(doc.section || "Unsorted", folderParts(doc).join("/"));

export function buildTree(documents: ArchiveDocument[]): TreeNode {
  const root: TreeNode = { key: "", name: "All documents", kind: "root", section: "", path: "", documents: [], children: [] };
  const child = (parent: TreeNode, name: string, kind: "section" | "folder", section: string, path: string) => {
    let node = parent.children.find(c => c.name === name);
    if (!node) {
      node = { key: nodeKey(section, path), name, kind, section, path, documents: [], children: [] };
      parent.children.push(node);
    }
    return node;
  };
  for (const doc of documents) {
    const section = doc.section || "Unsorted";
    root.documents.push(doc);
    let node = child(root, section, "section", section, "");
    node.documents.push(doc);
    const parts = folderParts(doc);
    parts.forEach((part, i) => {
      node = child(node, part, "folder", section, parts.slice(0, i + 1).join("/"));
      node.documents.push(doc);
    });
  }
  const sort = (node: TreeNode) => {
    node.children.sort((a, b) => collator.compare(a.name, b.name));
    node.children.forEach(sort);
  };
  sort(root);
  return root;
}

/** The documents filed in this exact folder (not in its subfolders). */
export function directDocuments(node: TreeNode): ArchiveDocument[] {
  return node.kind === "root" ? [] : node.documents.filter(d => docNodeKey(d) === node.key);
}

export function findNode(node: TreeNode, key: string): TreeNode | undefined {
  if (node.key === key) return node;
  for (const c of node.children) {
    const found = findNode(c, key);
    if (found) return found;
  }
  return undefined;
}

/** The nodes from the root down to ``key`` (just the root when it's not found). */
export function pathTo(root: TreeNode, key: string): TreeNode[] {
  const walk = (node: TreeNode): TreeNode[] | null => {
    if (node.key === key) return [node];
    for (const c of node.children) {
      const rest = walk(c);
      if (rest) return [node, ...rest];
    }
    return null;
  };
  return walk(root) ?? [root];
}

export function countFolders(node: TreeNode): number {
  return node.children.reduce((n, c) => n + (c.kind === "folder" ? 1 : 0) + countFolders(c), 0);
}

const sortValue: Record<SortKey, (d: ArchiveDocument) => string | number> = {
  title: d => d.title,
  location: d => `${d.section}/${d.folder}`,
  source: d => d.source,
  trust: d => d.source_trust,
  chunks: d => d.chunks_total,
  quarantined: d => d.chunks_quarantined,
  size: d => d.size_bytes,
  created: d => Date.parse(d.created_at) || 0,
};

export function sortDocuments(documents: ArchiveDocument[], key: SortKey, dir: SortDir): ArchiveDocument[] {
  const value = sortValue[key];
  const sign = dir === "asc" ? 1 : -1;
  return [...documents].sort((a, b) => {
    const va = value(a), vb = value(b);
    const primary = typeof va === "number" && typeof vb === "number" ? va - vb : collator.compare(String(va), String(vb));
    // Ties fall back to the name, then the id, so the order never jumps between refreshes.
    return sign * primary || collator.compare(a.title, b.title) || a.document_id.localeCompare(b.document_id);
  });
}

export function matchesQuery(doc: ArchiveDocument, query: string): boolean {
  const q = query.trim().toLocaleLowerCase();
  if (!q) return true;
  return [doc.title, doc.filename ?? "", doc.source, doc.section, doc.folder].some(v => v.toLocaleLowerCase().includes(q));
}

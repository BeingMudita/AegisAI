# Archive explorer

The Overview page lets administrators and security analysts browse the real knowledge base in three steps:

1. **Archive terrain** — each stack represents a section.
2. **Document anatomy** — each separated plate represents a folder in the chosen section. Folders open level by level (`Invoices` → `2026`), following the same tree as the Database page; files kept directly in a folder that also has subfolders appear as one extra *Files in …* layer.
3. **Document lineage** — the folder branches into documents; selecting a document expands its chunks. Select a chunk to read its passage, size and screening reason.

The entire application, including sign-in and every workspace page, uses a shared black, white and gray theme. It loads independently of Overview and replaces the previous light/dark/system palette switch. Buttons and selected controls use dark text on white surfaces. Colour is reserved for status, on one ordered scale used everywhere: **green** = approved / trusted / ready, **yellow** = medium / sanitized / pending, **orange** = low trust or untrusted source, **red** = blocked / harmful / quarantined. The four colours clear 3:1 contrast on the dark surfaces and stay distinguishable with colour-blindness, and status always comes with an icon, pattern or label as well. In the archive, Ready, Sanitized, Low trust and Blocked keep their distinct marks (square, half-fill, dashed outline, hatched diamond), every section, folder and document shows a thin bar of how its chunks split across the four, and chunk cards and branches carry their status colour. Transitions respect reduced-motion preferences. Search and pagination keep large archives navigable; chunk bodies load only for the selected document, 12 at a time.

## Organizing documents

Choose **Archive section** and **Archive folder** when uploading files, importing the server inbox, or pasting text in Knowledge base. These labels are separate from a document's source and trust level.

Use **Choose folder** or drag a folder onto the upload area to include supported files from every subfolder. The preview lists each file's relative path, and unsupported files are listed as skipped. Empty folders are not indexed. Large selections upload in batches of 25; if a request fails, previously accepted batches are removed from the selection so Retry uploads only the remaining files.

With the default `Unsorted / General` location, `Finance/Invoices/2026/bill.pdf` appears in section **Finance**, folder **Invoices/2026**. Files directly inside Finance appear in **General**. Nested folders open one level at a time in Document anatomy, and the breadcrumb shows the full path. A custom folder is a prefix; a custom section replaces the automatic section and retains a differently named root folder in the folder path. Server-inbox imports use the same rules. Loose files continue using the selected section and folder.

Existing documents default to **Unsorted / General**. To move one, open it in Document lineage, expand **Organize this document**, edit its section/folder and save. This is an administrator action. It changes metadata without re-indexing content. Folder imports distinguish identical content at different relative paths or archive locations, preserving separate copies. Uploading the same path, location and content again reports a duplicate. Loose-file uploads retain content-based duplicate detection. Paths stripped by older uploads cannot be reconstructed; reselect the original folder to import its structure.

Location metadata is saved with ingestion reports in the local index or PostgreSQL JSON metadata; no database migration is required. Existing files remain compatible.

## What the status means

- **Ready:** indexed during ingestion, with a source that currently passes the trust gate.
- **Sanitized:** flagged content was cleaned before indexing, and its source currently passes the trust gate.
- **Blocked:** the ingestion firewall quarantined this chunk; it is excluded from the vector index.
- **Low trust:** an indexed chunk whose source is declared untrusted (unless policy allows it) or whose current trust score is below policy.

The eligible count includes Ready and Sanitized. These states describe the stored ingestion result and current source gate, not a human approval. Query-time relevance and firewall checks still apply. Group block dimensions are illustrative, not a quantitative size chart.

In local index mode, quarantined content is retained as a 200-character excerpt. The inspector labels truncated passages and unavailable legacy size measurements. PostgreSQL retains the full quarantined passage. Token counts are estimates (characters divided by four), not tokenizer measurements.

## API

- `GET /api/retrieval/archive` — staff-only document metadata, location and current source eligibility.
- `GET /api/retrieval/documents/{id}/archive-chunks?offset=0&limit=12` — staff-only chunk index range, including quarantine; limit 1–50.
- `PUT /api/retrieval/documents/{id}/location` — administrator-only JSON body `{ "section": "Finance", "folder": "Invoices" }`.

## Verification

Backend regression tests: `python -m pytest tests/test_archive.py tests/test_rag.py tests/test_ingestion.py -q` from `backend/` with its virtual environment and `STORAGE_BACKEND=memory`.

Frontend: `npm test` and `npm run build` from `frontend/`.

On this Windows checkout, deleting the existing generated `dist/assets` directory currently returns `EPERM`. The build was verified with `npm run build -- --emptyOutDir=false`; this writes the updated application while retaining old, unreferenced generated assets. The source configuration is unchanged.

Real-stack browser tests: `npx playwright test --config playwright.archive.config.ts`. This starts isolated memory-only services on ports 15173 and 18000. On Windows, set `AEGIS_BROWSER_CHANNEL=msedge` to use installed Edge. The tests cover the journey, quarantine, pagination, saved locations, mobile width, loading failures, empty results and existing sign-in behavior. Screenshots are written beneath `frontend/test-results/`.

Validation for this change used the memory/local-index backend: 39 backend tests, 23 frontend tests and 5 browser tests passed, along with TypeScript, targeted Python type checks and lint. PostgreSQL support was updated and type-checked but was not exercised against a live database in this run.

## Database page

**Operate → Database** (staff) lists the whole knowledge base as a tree — section → folder → nested folders — next to a table of the documents in the chosen node. Sort by any column (or the *Sort* menu on small screens), search by name, file, source or folder, and open a document to page through its chunks with their status.

Administrators can delete one document, a selection (the header checkbox selects every document in the current view, across pages), or a whole folder or section. A confirmation lists what will be removed, with its chunk count and size. Deletion removes the documents, their chunks and quarantine records from the index and cannot be undone.

- `POST /api/retrieval/documents/delete` — administrator-only JSON body `{ "document_ids": ["…"] }` (1–1000 ids). Returns `{ "deleted": [...], "missing": [...] }`; the local index is saved once, and PostgreSQL deletes in one transaction.

### Vectors tab

The **Vectors** tab on the Database page shows the vector index itself: every indexed chunk with the embedding retrieval searches, filtered by the folder chosen in the tree, by text, or by screening result (clean / sanitized). The header shows where the index lives (in memory and saved to disk, or PostgreSQL + pgvector), the embedding model, dimensions, vector count and size.

Open a vector to see its text, its embedding (a strip of all dimensions — point at it or use the arrow keys to read values, or expand *Show all values*), and its five nearest neighbours by cosine similarity. **Open vector** on a chunk in the Documents tab jumps here.

Administrators can change a chunk's text or delete one vector:

- **Save and re-embed** runs the new text through the ingestion firewall, then recomputes the vector with the current embedding model. Text the firewall blocks is refused and nothing changes; flagged text is stored sanitized and counted on the document. Vectors are never edited by hand — they always come from the text, so retrieval stays consistent.
- **Delete vector** removes that one chunk and its vector; the document and its other chunks stay. Use the Documents tab to delete whole documents.

In memory mode every change rewrites the saved index on disk, which takes a few seconds for very large indexes. Edits and removals are logged (`knowledge_chunk_edited`, `knowledge_chunk_removed`), and flagged or blocked edit attempts are recorded as firewall security events.

- `GET /api/vectors/info` · `GET /api/vectors?section=&folder=&document_id=&q=&action=&offset=&limit=` · `GET /api/vectors/{chunk_id}` — staff.
- `PUT /api/vectors/{chunk_id}` with `{ "content": "…" }` (1–8000 characters) · `DELETE /api/vectors/{chunk_id}` — administrators. A blocked edit returns 422.

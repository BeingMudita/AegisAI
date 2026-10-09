/** Preserve browser-relative paths without reading file contents into memory. */
export interface UploadSelection { file: File; path: string }
export const ACCEPTED_DOCUMENTS = ".pdf,.docx,.txt,.md,.markdown,.log,.csv,.tsv,.json,.jsonl,.ndjson,.html,.htm";
const extensions = new Set(ACCEPTED_DOCUMENTS.split(","));
export const supportedDocument = (name: string) => extensions.has(name.slice(name.lastIndexOf(".")).toLowerCase());
export const uploadKey = ({ file, path }: UploadSelection) => JSON.stringify([path, file.size, file.lastModified]);

export function selectedFiles(list: FileList | File[]): UploadSelection[] {
  return Array.from(list).map(file => ({ file, path: file.webkitRelativePath || file.name }));
}

async function walkEntry(entry: FileSystemEntry, prefix = ""): Promise<UploadSelection[]> {
  const path = prefix + entry.name;
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) => (entry as FileSystemFileEntry).file(resolve, reject));
    return [{ file, path }];
  }
  if (!entry.isDirectory) return [];
  const reader = (entry as FileSystemDirectoryEntry).createReader();
  const files: UploadSelection[] = [];
  // Chromium returns directory entries in batches (often 100), not all at once.
  while (true) {
    const batch = await new Promise<FileSystemEntry[]>((resolve, reject) => reader.readEntries(resolve, reject));
    if (!batch.length) break;
    for (const child of batch) files.push(...await walkEntry(child, `${path}/`));
  }
  return files;
}

export function droppedFiles(transfer: DataTransfer): Promise<UploadSelection[]> {
  // Capture entries synchronously: the drag data store expires after the event.
  const entries = Array.from(transfer.items ?? []).filter(item => item.kind === "file").map(item => ({
    entry: item.webkitGetAsEntry?.(), file: item.getAsFile(),
  }));
  if (!entries.length) return Promise.resolve(selectedFiles(transfer.files));
  return Promise.all(entries.map(({ entry, file }) => entry ? walkEntry(entry) : Promise.resolve(file ? [{ file, path: file.name }] : []))).then(groups => groups.flat());
}

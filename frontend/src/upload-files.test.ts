import { describe, expect, it } from "vitest";
import { droppedFiles, selectedFiles, supportedDocument, uploadKey } from "./upload-files";

function entry(name: string): FileSystemEntry {
  return { name, isFile: true, isDirectory: false, file: (resolve: (f: File) => void) => resolve(new File([name], name)) } as unknown as FileSystemEntry;
}
function directory(name: string, batches: FileSystemEntry[][]): FileSystemEntry {
  let index = 0;
  return { name, isFile: false, isDirectory: true, createReader: () => ({ readEntries: (resolve: (entries: FileSystemEntry[]) => void) => resolve(batches[index++] ?? []) }) } as unknown as FileSystemEntry;
}

describe("folder file selection", () => {
  it("reads every directory batch and nested file, including duplicate basenames", async () => {
    const root = directory("Finance", [Array.from({ length: 100 }, (_, i) => entry(`${i}.txt`)), [
      directory("Invoices", [[entry("invoice.txt")]]), directory("Payroll", [[entry("invoice.txt")]]),
    ]]);
    const transfer = { items: [{ kind: "file", webkitGetAsEntry: () => root, getAsFile: () => null }] } as unknown as DataTransfer;
    const files = await droppedFiles(transfer);
    expect(files).toHaveLength(102);
    expect(files.slice(-2).map(f => f.path)).toEqual(["Finance/Invoices/invoice.txt", "Finance/Payroll/invoice.txt"]);
    expect(uploadKey(files[100])).not.toBe(uploadKey(files[101]));
  });
  it("keeps picker-relative paths and handles ordinary dropped files", async () => {
    const file = new File(["total 10"], "bill.txt");
    Object.defineProperty(file, "webkitRelativePath", { value: "Finance/Invoices/2026/bill.txt" });
    expect(selectedFiles([file])[0].path).toBe("Finance/Invoices/2026/bill.txt");
    expect(await droppedFiles({ items: [], files: [file] } as unknown as DataTransfer)).toEqual(selectedFiles([file]));
  });
  it("distinguishes supported documents from unsupported directory contents", () => {
    expect(supportedDocument("BILL.PDF")).toBe(true);
    expect(supportedDocument("data.jsonl")).toBe(true);
    expect(supportedDocument("Finance")).toBe(false);
    expect(supportedDocument("logo.png")).toBe(false);
  });
});

/** Export structured evidence without interpreting untrusted content as HTML or CSV. */
export function downloadJson(filename: string, value: unknown): void {
  download(filename, JSON.stringify(value, null, 2), "application/json");
}

/** Download arbitrary text (e.g. a generated aegis.yaml) as a file. */
export function downloadText(filename: string, text: string, type = "text/plain"): void {
  download(filename, text, type);
}

function download(filename: string, content: string, type: string): void {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

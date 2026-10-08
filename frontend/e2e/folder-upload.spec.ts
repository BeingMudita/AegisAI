import { expect, test } from "@playwright/test";
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";
import { tmpdir } from "node:os";

test("folder picker uploads nested files, keeps copies and retries only remaining batches", async ({ page, request }) => {
  test.setTimeout(60000);
  const temp = await mkdtemp(join(tmpdir(), "aegis-folder-test-"));
  const root = join(temp, "Finance");
  await mkdir(join(root, "Invoices", "2026"), { recursive: true });
  await mkdir(join(root, "Payroll"), { recursive: true });
  for (let i = 0; i < 101; i++) await writeFile(join(root, "Invoices", "2026", `invoice-${i}.txt`), `Invoice ${i} total ${i + 300}.`);
  await writeFile(join(root, "Invoices", "2026", "copy.txt"), "The shared invoice total is 71.");
  await writeFile(join(root, "Payroll", "copy.txt"), "The shared invoice total is 71.");
  await writeFile(join(root, "readme.txt"), "Finance archive for the upload test.");
  await writeFile(join(root, "logo.png"), "unsupported image fixture");
  const login = await request.post("/api/auth/login", { form: { username: "admin", password: "admin123" } });
  const headers = { Authorization: `Bearer ${(await login.json()).access_token}` };
  try {
    await page.goto("/#/knowledge");
    await page.getByLabel("Username").fill("admin");
    await page.getByLabel("Password").fill("admin123");
    await page.getByRole("button", { name: /continue to workspace/i }).click();
    await page.getByLabel("Folder to upload", { exact: true }).setInputFiles(root);
    await expect(page.getByRole("button", { name: "Upload 104 files", exact: true })).toBeVisible();
    await expect(page.getByText("Skipped 1 unsupported files", { exact: true })).toBeVisible();
    await expect(page.getByTitle("Finance/Invoices/2026/invoice-0.txt", { exact: true })).toBeVisible();
    let batches = 0;
    await page.route("**/api/retrieval/uploads", async route => {
      if (++batches === 2) await route.fulfill({ status: 503, json: { detail: "Temporary upload failure" } });
      else await route.continue();
    });
    await page.getByRole("button", { name: "Upload 104 files", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("Temporary upload failure");
    await expect(page.getByRole("button", { name: "Upload 79 files", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Upload 79 files", exact: true }).click();
    await expect(page.getByText("79 files queued for processing.", { exact: false })).toBeVisible();
    await expect.poll(async () => {
      const docs = await (await request.get("/api/retrieval/archive", { headers })).json();
      return docs.filter((doc: { section: string }) => doc.section === "Finance").length;
    }, { timeout: 30000 }).toBe(104);
    const docs = (await (await request.get("/api/retrieval/archive", { headers })).json()).filter((d: { section: string }) => d.section === "Finance");
    expect(docs.filter((d: { folder: string }) => d.folder === "Invoices/2026")).toHaveLength(102);
    expect(docs.filter((d: { title: string }) => d.title === "copy.txt")).toHaveLength(2);
    expect(docs.find((d: { filename: string }) => d.filename === "Finance/Payroll/copy.txt").folder).toBe("Payroll");
    await page.getByRole("button", { name: "Overview", exact: true }).click();
    await page.getByRole("button", { name: "Open section Finance", exact: true }).click();
    // Nested folders open level by level, as in the Database tree.
    await page.getByRole("button", { name: "Open folder Invoices", exact: true }).click();
    await page.getByRole("button", { name: "Open folder 2026", exact: true }).click();
    await expect(page.locator(".aj-doc-node").first()).toBeVisible();
    await expect(page.getByLabel("Archive breadcrumb")).toContainText("Finance/Invoices/2026");
  } finally {
    const docs = await (await request.get("/api/retrieval/archive", { headers })).json();
    for (const doc of docs.filter((d: { section: string }) => d.section === "Finance")) await request.delete(`/api/retrieval/documents/${doc.document_id}`, { headers });
    expect(dirname(resolve(temp))).toBe(resolve(tmpdir()));
    expect(basename(temp).startsWith("aegis-folder-test-")).toBe(true);
    await rm(temp, { recursive: true, force: true });
  }
});

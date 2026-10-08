import { defineConfig, devices } from "@playwright/test";

// Isolated real-stack validation: no persisted index or existing dev server is used.
const python = process.env.AEGIS_PY ?? (process.platform === "win32" ? ".venv\\Scripts\\python.exe" : ".venv/bin/python");
export default defineConfig({
  testDir: "./e2e",
  testMatch: ["archive.spec.ts", "auth.spec.ts", "folder-upload.spec.ts"],
  workers: 1,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:15173", trace: "retain-on-failure" },
  projects: [{ name: "archive", use: { ...devices["Desktop Chrome"], channel: process.env.AEGIS_BROWSER_CHANNEL || undefined } }],
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --host 127.0.0.1 --port 18000`,
      cwd: "../backend", url: "http://127.0.0.1:18000/health", reuseExistingServer: false,
      env: { STORAGE_BACKEND: "memory", LLM_BACKEND: "rule_based", EMBEDDING_BACKEND: "hashing", RAG_PERSIST: "false", RAG_SEED_CORPUS: "true", DATA_DIR: "../frontend/test-results/archive-data", JWT_SECRET: "archive-e2e-isolated-local-test-key-2026" },
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 15173 --strictPort",
      url: "http://127.0.0.1:15173", reuseExistingServer: false,
      env: { AEGIS_API_TARGET: "http://127.0.0.1:18000" },
    },
  ],
});

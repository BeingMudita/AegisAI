import { defineConfig, devices } from "@playwright/test";

// End-to-end tests drive the real stack in a browser: the FastAPI backend
// (in-memory, seeded accounts) and the Vite dev server (which proxies /api to
// the backend). Playwright starts both unless they are already running.

// Local runs use the backend virtualenv; CI (which pip-installs into the system
// interpreter) overrides this with AEGIS_PY=python.
const isWin = process.platform === "win32";
const python = process.env.AEGIS_PY ?? (isWin ? ".venv\\Scripts\\python.exe" : ".venv/bin/python");

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --port 8000`,
      cwd: "../backend",
      url: "http://localhost:8000/health",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      // Deterministic offline backends; RAG_PERSIST off so E2E never writes the
      // committed on-disk index (and can't contend for its file lock).
      env: {
        LLM_BACKEND: "rule_based",
        EMBEDDING_BACKEND: "hashing",
        RAG_PERSIST: "false",
      },
    },
    {
      command: "npm run dev",
      url: "http://localhost:5173",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});

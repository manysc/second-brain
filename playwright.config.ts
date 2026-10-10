import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

// End-to-end smoke suite over the real stack: Postgres + SeaweedFS (docker compose), the FastAPI backend and Next.js.
// Both servers are started here unless already running; the backend skips its startup ingest so a run is quick and
// does not race the suite. Every test works on a dataset seeded per run (see backend/tests/e2e_fixture.py).
const python = path.join(process.cwd(), "backend", ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");

export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: false,
  workers: 1, // one shared database
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  globalSetup: "./tests/e2e/global-setup.ts",
  globalTeardown: "./tests/e2e/global-teardown.ts",
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    // Chromium downloads can be blocked by TLS interception; an installed Edge works the same. PW_CHANNEL=chromium
    // (after `npx playwright install chromium`) or chrome overrides it.
    ...devices["Desktop Chrome"],
    channel: process.env.PW_CHANNEL ?? "msedge",
  },
  webServer: [
    {
      command: `"${python}" -m uvicorn app.main:app --port 8000`,
      cwd: "backend",
      url: "http://127.0.0.1:8000/api/topics",
      env: { INGEST_ON_STARTUP: "false" },
      reuseExistingServer: true,
      timeout: 180_000,
    },
    {
      command: "npm run dev",
      url: "http://127.0.0.1:3000/topics",
      env: { API_BASE_URL: "http://127.0.0.1:8000" },
      reuseExistingServer: true,
      timeout: 180_000,
    },
  ],
});

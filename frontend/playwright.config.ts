import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against a running stack: the web app on BASE_URL (default
 * http://localhost:3000) and the API behind it. Start them first:
 *
 *   docker compose up -d db kv
 *   (backend)  uv run uvicorn vicky.api:app --port 8000
 *   (frontend) npm run dev
 *   npm run test:e2e
 *
 * Global setup signs in with ACCESS_CODE (default: the local dev code) and makes sure a confirmed
 * source of truth exists, loading the first sample if there is none. Tests run one at a time
 * because they share that dashboard; any widget a test adds is removed again.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:3000",
    storageState: "e2e/.auth/state.json",
    viewport: { width: 1440, height: 900 },
    colorScheme: "dark",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
});

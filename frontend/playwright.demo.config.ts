import { defineConfig, devices } from "@playwright/test";

/**
 * Demo videos, one per tab, recorded against a running stack (see `demo/README.md`). Not part of
 * the E2E suite: these click through the app at a human pace with a visible cursor and captions,
 * and save each recording to `../docs/demo/raw/`. `npm run demo:videos` then encodes MP4 and GIF.
 *
 *   npm run build && npx next start -p 3100
 *   BASE_URL=http://localhost:3100 npm run demo:record
 */
export default defineConfig({
  testDir: "./demo",
  testMatch: "*.demo.ts",
  outputDir: "./demo/.out",
  timeout: 6 * 60_000,
  expect: { timeout: 60_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:3000",
    viewport: { width: 1440, height: 900 },
    colorScheme: "dark",
    video: { mode: "on", size: { width: 1440, height: 900 } },
    actionTimeout: 30_000,
    launchOptions: {
      // WebGL (the VICKY mark, the readiness orb) needs a software GL in headless runs.
      args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist", "--autoplay-policy=no-user-gesture-required"],
    },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 } }],
});

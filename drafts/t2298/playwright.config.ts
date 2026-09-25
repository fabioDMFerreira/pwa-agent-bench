import { defineConfig } from "@playwright/test";

/**
 * Playwright configuration for task #2298 E2E specs.
 *
 * Assumes the Express app in src/server/main.ts is booted with the demo user
 * mounted at /demo/tasks. The webServer block spins up that app for the
 * duration of the test run.
 */
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: true,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:4318",
    trace: "on-first-retry",
  },
  webServer: {
    command: "npm run serve",
    url: "http://localhost:4318/healthz",
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
    env: { PORT: "4318" },
  },
});

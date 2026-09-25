import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    include: [
      "src/**/*.test.{ts,tsx}",
      "tests/api/**/*.spec.{ts,tsx}",
      "tests/e2e/demo-page-integration.spec.ts",
    ],
    // The Playwright specs run separately with `npx playwright test`; keep
    // them out of the vitest suite.
    exclude: ["node_modules", "tests/e2e/column-picker.spec.ts"],
    setupFiles: ["./vitest.setup.ts"],
  },
});

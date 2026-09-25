// Vitest setup: bring in jest-dom matchers and install a fetch fallback for
// tests that don't override it explicitly. Also normalise NODE_ENV so React's
// act() helper works even when the ambient env has NODE_ENV=production
// (some sandbox environments set this globally).
if (process.env.NODE_ENV === "production") {
  process.env.NODE_ENV = "test";
}

import "@testing-library/jest-dom/vitest";

if (typeof globalThis.fetch !== "function") {
  globalThis.fetch = async () =>
    new Response("not implemented", { status: 501 });
}

// Composes the Express app used by both the API tests (via supertest) and
// the E2E demo page. Nothing here is production-grade — it exists so the
// same routes can be exercised without an entire PWA stack.

import express, { type Express } from "express";
import { createPreferencesRouter, PREF_KEY } from "./preferences.js";
import { createMemoryStore, type PreferenceStore } from "./store.js";
import { headerAuth } from "./auth.js";
import { renderDemoPage } from "./demoPage.js";
import { getFlag, setFlag } from "./flags.js";

export interface AppDeps {
  store?: PreferenceStore;
}

export function createApp(deps: AppDeps = {}): {
  app: Express;
  store: PreferenceStore;
} {
  const store = deps.store ?? createMemoryStore();
  const app = express();

  app.use(express.json());
  app.use(headerAuth);

  app.get("/healthz", (_req, res) => {
    res.status(200).json({ ok: true });
  });

  // Feature-flag admin (test helper — not exposed in production).
  app.get("/api/flags/:name", (req, res) => {
    res.json({ name: req.params.name, enabled: getFlag(req.params.name) });
  });
  app.put("/api/flags/:name", (req, res) => {
    const enabled = Boolean((req.body ?? {}).enabled);
    setFlag(req.params.name, enabled);
    res.json({ name: req.params.name, enabled });
  });

  app.use(
    `/api/preferences/${PREF_KEY}`,
    createPreferencesRouter({ store }),
  );

  // Demo page for Playwright: server-renders a minimal HTML page that boots
  // the React table. The page reads x-demo-user via the loader script.
  app.get("/demo/tasks", (req, res) => {
    const user =
      (req.query.user as string | undefined)?.trim() || "demo-user-1";
    res.type("html").send(renderDemoPage(user));
  });

  return { app, store };
}

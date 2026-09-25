// /api/preferences/tasks.table.columns
//
// GET    → 200 with the stored preference, or 404 (no row) or 401 (no user).
// PUT    → 200 with the sanitised, persisted value.
// DELETE → 204 (idempotent; still 204 when there is no row).
//
// The router owns validation, sanitisation, locked-on injection, and the
// EMPTY_VISIBLE guard. That logic lives here (not in <ColumnPicker/>) because
// the server is the single truth against a scripted client.

import { Router } from "express";
import type { Response } from "express";
import { sanitizeVisible } from "../features/tasks/table/columnDefs.js";
import {
  CURRENT_VERSION,
  ErrorCodes,
  TaskColumnsPref,
} from "../shared/schema.js";
import { requireUser, type AuthedRequest } from "./auth.js";
import type { PreferenceStore } from "./store.js";

export const PREF_KEY = "tasks.table.columns" as const;

export interface PreferencesRouterDeps {
  store: PreferenceStore;
}

export function createPreferencesRouter(deps: PreferencesRouterDeps): Router {
  const router = Router();
  router.use(requireUser);

  router.get("/", (req: AuthedRequest, res: Response) => {
    const row = deps.store.get(req.userId!, PREF_KEY);
    if (!row) {
      res
        .status(404)
        .json({ error: { code: ErrorCodes.NOT_FOUND, message: "no row" } });
      return;
    }
    res.status(200).json(row);
  });

  router.put("/", (req: AuthedRequest, res: Response) => {
    const parsed = TaskColumnsPref.safeParse(req.body);
    if (!parsed.success) {
      const versionIssue = parsed.error.issues.find((i) =>
        i.path.includes("version"),
      );
      if (versionIssue) {
        res.status(400).json({
          error: {
            code: ErrorCodes.VERSION_MISMATCH,
            message: `expected version ${CURRENT_VERSION}`,
          },
        });
        return;
      }
      res.status(400).json({
        error: {
          code: ErrorCodes.INVALID_BODY,
          message: "payload failed validation",
          issues: parsed.error.issues,
        },
      });
      return;
    }

    const visible = sanitizeVisible(parsed.data.visible);
    // sanitizeVisible ALWAYS re-adds locked-on ids, so `visible` can only be
    // empty if LOCKED_ON is empty AND every stored id was unknown. Reject
    // that case explicitly with a stable code so the client can surface it.
    const strippedFromInput =
      parsed.data.visible.length > 0 &&
      parsed.data.visible.every(
        (id) => !visible.includes(id as (typeof visible)[number]),
      );
    if (visible.length === 0 || strippedFromInput) {
      res.status(400).json({
        error: {
          code: ErrorCodes.EMPTY_VISIBLE,
          message: "visible is empty after stripping unknown ids",
        },
      });
      return;
    }

    // `order` must be a superset of `visible`; anything not in `visible`
    // is preserved (for future reorder support) but unknown ids are dropped.
    const order = sanitizeVisible([...parsed.data.order, ...visible]);

    const clean: TaskColumnsPref = {
      version: CURRENT_VERSION,
      visible,
      order,
      widths: parsed.data.widths,
    };
    deps.store.set(req.userId!, PREF_KEY, clean);
    res.status(200).json(clean);
  });

  router.delete("/", (req: AuthedRequest, res: Response) => {
    deps.store.delete(req.userId!, PREF_KEY);
    res.status(204).end();
  });

  return router;
}

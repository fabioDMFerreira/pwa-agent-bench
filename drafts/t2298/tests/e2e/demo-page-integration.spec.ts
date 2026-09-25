/**
 * End-to-end style coverage for the /demo/tasks page WITHOUT a real browser.
 *
 * The Playwright spec in `column-picker.spec.ts` is the canonical E2E — but
 * it needs system libraries (libglib etc.) that aren't installable in the
 * benchmark sandbox. This file boots the real Express server + serves the
 * same HTML into JSDOM, then drives it through the same scenarios so the
 * behaviour is executable in CI even where Playwright can't run.
 *
 * Coverage: default state, toggle+persist+PUT-batching, locked-on, reset,
 * forward-compat with retired columns, feature-flag off.
 */

import { describe, beforeAll, afterAll, beforeEach, expect, it } from "vitest";
import { AddressInfo } from "node:net";
import { Server } from "node:http";
import { JSDOM, VirtualConsole } from "jsdom";
import { createApp } from "../../src/server/app.js";
import { setFlag } from "../../src/server/flags.js";
import { createMemoryStore } from "../../src/server/store.js";

let server: Server;
let baseUrl: string;
const store = createMemoryStore();

beforeAll(async () => {
  const { app } = createApp({ store });
  await new Promise<void>((resolve) => {
    server = app.listen(0, () => resolve());
  });
  const port = (server.address() as AddressInfo).port;
  baseUrl = `http://localhost:${port}`;
});

afterAll(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

beforeEach(() => {
  store.reset();
  setFlag("tasks.customColumns", true);
});

async function bootPage(userId: string): Promise<{ dom: JSDOM; window: Window }> {
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("error", (e) => {
    // eslint-disable-next-line no-console
    console.error("[jsdom]", e);
  });
  // JSDOM doesn't ship fetch on its window; fetch first, then inject a
  // fetch polyfill before the demo page's inline script runs.
  const htmlRes = await fetch(`${baseUrl}/demo/tasks?user=${userId}`);
  const html = await htmlRes.text();
  const dom = new JSDOM(html, {
    url: `${baseUrl}/demo/tasks?user=${userId}`,
    runScripts: "dangerously",
    virtualConsole,
    pretendToBeVisual: true,
    beforeParse(win) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (win as any).fetch = (input: any, init: any) => {
        const url =
          typeof input === "string"
            ? new URL(input, baseUrl).toString()
            : input.url;
        return fetch(url, init);
      };
    },
  });
  const window = dom.window as unknown as Window;
  const doc = dom.window.document;
  await waitUntil(() => doc.body.getAttribute("data-loaded") === "true", 2000);
  return { dom, window };
}

async function waitUntil(cond: () => boolean, timeoutMs: number) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (cond()) return;
    await new Promise((r) => setTimeout(r, 25));
  }
  throw new Error("timed out waiting for condition");
}

function headers(doc: Document): string[] {
  return Array.from(doc.querySelectorAll("#task-thead th")).map(
    (th) => th.getAttribute("data-column") ?? "",
  );
}

const DEFAULT_VISIBLE = [
  "id",
  "title",
  "status",
  "priority",
  "category",
  "assignee",
  "dueDate",
  "updatedAt",
];

describe("/demo/tasks — integration", () => {
  it("scenario 1: default state shows DEFAULT_VISIBLE column set", async () => {
    const { dom } = await bootPage("int-default");
    expect(headers(dom.window.document)).toEqual(DEFAULT_VISIBLE);
  });

  it("scenario 2: toggle hides the column, one PUT after debounce, survives reload", async () => {
    const user = "int-toggle";
    const { dom, window } = await bootPage(user);
    const doc = dom.window.document;
    // Open picker.
    (doc.getElementById("columns-btn") as HTMLButtonElement).click();
    const cb = doc.querySelector(
      '[data-testid="col-checkbox-assignee"]',
    ) as HTMLInputElement;
    cb.click();
    expect(headers(doc)).not.toContain("assignee");

    // Wait for the debounced PUT to flush.
    await waitUntil(
      () => (window as unknown as { __putCount: number }).__putCount === 1,
      1500,
    );

    // Reload by booting a second JSDOM instance for the same user.
    const { dom: dom2 } = await bootPage(user);
    expect(headers(dom2.window.document)).not.toContain("assignee");
    expect(headers(dom2.window.document)).toContain("id");
  });

  it("scenario 3: locked-on rows are disabled and clicking does nothing", async () => {
    const { dom } = await bootPage("int-locked");
    const doc = dom.window.document;
    (doc.getElementById("columns-btn") as HTMLButtonElement).click();
    for (const id of ["id", "title"]) {
      const cb = doc.querySelector(
        `[data-testid="col-checkbox-${id}"]`,
      ) as HTMLInputElement;
      expect(cb.disabled).toBe(true);
      expect(cb.checked).toBe(true);
    }
    const before = headers(doc);
    const titleCb = doc.querySelector(
      '[data-testid="col-checkbox-title"]',
    ) as HTMLInputElement;
    titleCb.click();
    expect(headers(doc)).toEqual(before);
  });

  it("scenario 4: reset restores DEFAULT_VISIBLE and survives reload", async () => {
    const user = "int-reset";
    const { dom, window } = await bootPage(user);
    const doc = dom.window.document;
    (doc.getElementById("columns-btn") as HTMLButtonElement).click();
    (
      doc.querySelector('[data-testid="col-checkbox-priority"]') as HTMLInputElement
    ).click();
    (
      doc.querySelector('[data-testid="col-checkbox-assignee"]') as HTMLInputElement
    ).click();
    (
      doc.querySelector('[data-testid="col-checkbox-updatedAt"]') as HTMLInputElement
    ).click();
    await waitUntil(
      () => (window as unknown as { __putCount: number }).__putCount === 1,
      1500,
    );

    (doc.getElementById("reset-btn") as HTMLButtonElement).click();
    // Reset dispatches an async DELETE; wait until headers snap back.
    await waitUntil(
      () => headers(doc).join(",") === DEFAULT_VISIBLE.join(","),
      2000,
    );

    const { dom: dom2 } = await bootPage(user);
    expect(headers(dom2.window.document)).toEqual(DEFAULT_VISIBLE);
  });

  it("scenario 6: retired column id in stored row is dropped, no crash", async () => {
    const user = "int-compat";
    // Seed the store directly with a mixed valid/invalid id list.
    store.set(user, "tasks.table.columns", {
      version: 1,
      visible: ["id", "title", "status", "retired_column"],
      order: ["id", "title", "status", "retired_column"],
      widths: {},
    });
    const { dom } = await bootPage(user);
    expect(headers(dom.window.document)).toEqual(["id", "title", "status"]);
  });

  it("scenario 7: feature flag off → no Columns button", async () => {
    setFlag("tasks.customColumns", false);
    const { dom } = await bootPage("int-flagoff");
    const btn = dom.window.document.getElementById(
      "columns-btn",
    ) as HTMLButtonElement | null;
    // Button is present in the DOM but stays hidden (mimics the React
    // path where the ColumnPicker isn't mounted at all).
    expect(btn?.hidden).toBe(true);
    // Table still renders.
    expect(headers(dom.window.document).length).toBeGreaterThan(0);
  });
});

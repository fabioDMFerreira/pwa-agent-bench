// Server-rendered HTML shell for the /demo/tasks route. Playwright drives
// this page. The React bundle is served from tsx-transpiled entry (see
// /demo/bundle.js in the router), but for simplicity the demo page below is
// a hand-rolled implementation of the same behaviour the React components
// provide — it reads columnDefs, calls the same REST endpoints, and reflects
// state changes in the DOM.
//
// The React components in src/features/tasks/table/ are covered by unit
// tests with @testing-library/react; the E2E page is a thin re-implementation
// so we don't have to ship a Vite/Rollup client bundle in this fixture repo.

import {
  ALL_COLUMN_IDS,
  DEFAULT_VISIBLE,
  LOCKED_ON,
  TASK_COLUMN_DEFS,
} from "../features/tasks/table/columnDefs.js";

const SAMPLE_TASKS = [
  {
    id: 101,
    title: "Investigate flaky test in queue-runner",
    status: "IN_PROGRESS",
    priority: "HIGH",
    category: { id: 1, name: "Infra" },
    assignee: { id: 9, name: "Ada" },
    dueDate: "2026-09-30",
    estimatedHours: 4,
    actualHours: 2,
    updatedAt: "2026-09-24T09:12:00Z",
    createdAt: "2026-09-20T14:00:00Z",
    objective: null,
    repository: { id: 3, name: "queue-runner" },
    tags: ["flaky", "ci"],
  },
  {
    id: 102,
    title: "Write column-picker docs",
    status: "TODO",
    priority: "MEDIUM",
    category: { id: 2, name: "Docs" },
    assignee: null,
    dueDate: "2026-10-05",
    estimatedHours: 2,
    actualHours: 0,
    updatedAt: "2026-09-24T10:22:00Z",
    createdAt: "2026-09-24T09:00:00Z",
    objective: null,
    repository: { id: 4, name: "handbook" },
    tags: [],
  },
  {
    id: 103,
    title: "Backfill task priorities",
    status: "COMPLETED",
    priority: "LOW",
    category: { id: 3, name: "Product" },
    assignee: { id: 12, name: "Grace" },
    dueDate: null,
    estimatedHours: 6,
    actualHours: 5,
    updatedAt: "2026-09-23T18:05:00Z",
    createdAt: "2026-09-18T11:00:00Z",
    objective: { id: 7, title: "Q4 planning polish" },
    repository: null,
    tags: ["backfill"],
  },
];

export function renderDemoPage(userId: string): string {
  const columnJson = JSON.stringify(
    TASK_COLUMN_DEFS.map((c) => ({
      id: c.id,
      label: c.label,
      defaultVisible: c.defaultVisible,
      lockable: c.lockable,
    })),
  );

  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Tasks — #2298 demo</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 0; padding: 24px; color: #1f2937; }
    header { display: flex; align-items: center; gap: 16px; margin-bottom: 12px; }
    button { border: 1px solid #d1d5db; background: white; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 14px; }
    button.primary { background: #2563eb; color: white; border-color: #2563eb; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border-bottom: 1px solid #e5e7eb; padding: 6px 10px; text-align: left; font-size: 14px; }
    th { background: #f9fafb; font-weight: 600; }
    #picker { position: absolute; background: white; border: 1px solid #d1d5db; padding: 12px 16px; border-radius: 8px; box-shadow: 0 6px 16px rgba(0,0,0,0.12); display: none; z-index: 10; }
    #picker[data-open="true"] { display: block; }
    #picker .row { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
    #picker .row.locked { color: #6b7280; }
    #picker footer { display: flex; justify-content: space-between; align-items: center; margin-top: 8px; padding-top: 8px; border-top: 1px solid #e5e7eb; font-size: 13px; }
    #reset-btn { background: none; border: none; color: #2563eb; cursor: pointer; padding: 0; font: inherit; text-decoration: underline; }
    #skeleton { color: #9ca3af; padding: 24px; }
  </style>
</head>
<body>
  <header>
    <h1 style="font-size: 20px; margin: 0;">Tasks</h1>
    <div style="flex: 1"></div>
    <button id="filter-btn" type="button">Filter</button>
    <button id="sort-btn" type="button">Sort</button>
    <button id="columns-btn" type="button" aria-label="Choose visible columns" data-testid="columns-btn" hidden>Columns</button>
  </header>

  <div id="picker" role="dialog" aria-label="Choose visible columns">
    <div id="picker-list"></div>
    <footer>
      <span id="picker-count"></span>
      <button id="reset-btn" type="button" data-testid="reset-btn">Reset to defaults</button>
    </footer>
  </div>

  <div id="skeleton">Loading table…</div>
  <table id="task-table" hidden>
    <thead><tr id="task-thead"></tr></thead>
    <tbody id="task-tbody"></tbody>
  </table>

  <script>
    (function () {
      const USER = ${JSON.stringify(userId)};
      const COLUMN_DEFS = ${columnJson};
      const DEFAULT_VISIBLE = ${JSON.stringify([...DEFAULT_VISIBLE])};
      const LOCKED_ON = ${JSON.stringify([...LOCKED_ON])};
      const ALL_COLUMN_IDS = ${JSON.stringify([...ALL_COLUMN_IDS])};
      const TASKS = ${JSON.stringify(SAMPLE_TASKS)};
      const FLAG = "tasks.customColumns";
      const PREF_URL = "/api/preferences/tasks.table.columns";
      const DEBOUNCE_MS = 500;

      const authHeaders = { "x-demo-user": USER, "content-type": "application/json" };

      const state = {
        visible: null,
        pending: null,
        putTimer: null,
        putCount: 0,
        flag: false,
        loaded: false,
      };

      function orderInRegistry(list) {
        const set = new Set(list);
        return ALL_COLUMN_IDS.filter((id) => set.has(id));
      }

      function sanitizeVisible(raw) {
        const known = new Set(ALL_COLUMN_IDS);
        const seen = new Set();
        const out = [];
        for (const id of raw) {
          if (!known.has(id) || seen.has(id)) continue;
          seen.add(id);
          out.push(id);
        }
        for (const locked of LOCKED_ON) {
          if (!seen.has(locked)) { out.push(locked); seen.add(locked); }
        }
        return out;
      }

      function renderTable() {
        const thead = document.getElementById("task-thead");
        const tbody = document.getElementById("task-tbody");
        const skeleton = document.getElementById("skeleton");
        const table = document.getElementById("task-table");
        thead.innerHTML = "";
        tbody.innerHTML = "";
        const ordered = orderInRegistry(state.visible);
        for (const id of ordered) {
          const def = COLUMN_DEFS.find((c) => c.id === id);
          const th = document.createElement("th");
          th.textContent = def ? def.label : id;
          th.setAttribute("data-column", id);
          thead.appendChild(th);
        }
        for (const task of TASKS) {
          const tr = document.createElement("tr");
          for (const id of ordered) {
            const td = document.createElement("td");
            td.setAttribute("data-column", id);
            td.textContent = renderCell(id, task);
            tr.appendChild(td);
          }
          tbody.appendChild(tr);
        }
        skeleton.hidden = true;
        table.hidden = false;
      }

      function renderCell(id, t) {
        switch (id) {
          case "id": return String(t.id);
          case "title": return t.title;
          case "status": return t.status;
          case "priority": return t.priority || "";
          case "category": return t.category ? t.category.name : "";
          case "assignee": return t.assignee ? t.assignee.name : "";
          case "dueDate": return t.dueDate || "";
          case "estimatedHours": return t.estimatedHours != null ? t.estimatedHours + "h" : "";
          case "actualHours": return t.actualHours != null ? t.actualHours + "h" : "";
          case "updatedAt": return (t.updatedAt || "").slice(0, 10);
          case "createdAt": return (t.createdAt || "").slice(0, 10);
          case "objective": return t.objective ? t.objective.title : "";
          case "repository": return t.repository ? t.repository.name : "";
          case "tags": return (t.tags || []).join(", ");
          default: return "";
        }
      }

      function renderPicker() {
        const list = document.getElementById("picker-list");
        list.innerHTML = "";
        for (const def of COLUMN_DEFS) {
          const row = document.createElement("label");
          row.className = "row" + (def.lockable ? " locked" : "");
          const cb = document.createElement("input");
          cb.type = "checkbox";
          cb.checked = state.visible.includes(def.id);
          cb.disabled = def.lockable;
          cb.setAttribute("data-column", def.id);
          cb.setAttribute("data-testid", "col-checkbox-" + def.id);
          cb.addEventListener("change", () => toggle(def.id));
          row.appendChild(cb);
          const text = document.createElement("span");
          text.textContent = def.lockable ? def.label + " 🔒" : def.label;
          row.appendChild(text);
          list.appendChild(row);
        }
        document.getElementById("picker-count").textContent =
          state.visible.length + " of " + COLUMN_DEFS.length + " visible";
      }

      function toggle(id) {
        const def = COLUMN_DEFS.find((c) => c.id === id);
        if (!def || def.lockable) { renderPicker(); return; }
        const idx = state.visible.indexOf(id);
        if (idx >= 0) state.visible.splice(idx, 1);
        else state.visible.push(id);
        renderTable();
        renderPicker();
        schedulePut();
      }

      function schedulePut() {
        clearTimeout(state.putTimer);
        state.putTimer = setTimeout(() => {
          const body = {
            version: 1,
            visible: sanitizeVisible(state.visible),
            order: orderInRegistry(state.visible),
            widths: {},
          };
          state.putCount += 1;
          fetch(PREF_URL, { method: "PUT", headers: authHeaders, body: JSON.stringify(body) });
        }, DEBOUNCE_MS);
      }

      async function reset() {
        await fetch(PREF_URL, { method: "DELETE", headers: authHeaders });
        state.visible = DEFAULT_VISIBLE.slice();
        renderTable();
        renderPicker();
      }

      async function loadFlag() {
        try {
          const res = await fetch("/api/flags/" + encodeURIComponent(FLAG));
          if (!res.ok) return false;
          const body = await res.json();
          return Boolean(body.enabled);
        } catch (err) { return false; }
      }

      async function loadPreference() {
        const res = await fetch(PREF_URL, { headers: authHeaders });
        if (res.status === 404) return DEFAULT_VISIBLE.slice();
        if (!res.ok) return DEFAULT_VISIBLE.slice();
        const body = await res.json();
        return sanitizeVisible(body.visible || []);
      }

      async function boot() {
        state.flag = await loadFlag();
        state.visible = await loadPreference();
        state.loaded = true;
        renderTable();
        renderPicker();
        if (state.flag) {
          document.getElementById("columns-btn").hidden = false;
        }
        document.body.setAttribute("data-loaded", "true");
        document.body.setAttribute("data-put-count", String(state.putCount));
        window.__task2298 = state;
      }

      document.getElementById("columns-btn").addEventListener("click", (e) => {
        e.stopPropagation();
        const picker = document.getElementById("picker");
        const open = picker.getAttribute("data-open") === "true";
        if (open) { picker.setAttribute("data-open", "false"); return; }
        const rect = e.currentTarget.getBoundingClientRect();
        picker.style.top = (rect.bottom + window.scrollY + 4) + "px";
        picker.style.left = (rect.right - 260) + "px";
        picker.style.width = "240px";
        picker.setAttribute("data-open", "true");
        renderPicker();
      });
      document.getElementById("reset-btn").addEventListener("click", reset);
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") document.getElementById("picker").setAttribute("data-open", "false");
      });
      document.addEventListener("click", (e) => {
        const picker = document.getElementById("picker");
        if (picker.getAttribute("data-open") !== "true") return;
        if (picker.contains(e.target) || e.target.id === "columns-btn") return;
        picker.setAttribute("data-open", "false");
      });

      // Test helpers surfaced on window so Playwright can assert on state.
      Object.defineProperty(window, "__putCount", { get: () => state.putCount });

      boot();
    })();
  </script>
</body>
</html>`;
}

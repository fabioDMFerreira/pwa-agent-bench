# Proposal — Task #2298 · Selectable task-table columns, persisted in user preferences

**Deliverable set (in this folder)**

| File | What it is |
|---|---|
| `PROPOSAL.md` | This file — executive summary + design decisions. |
| `mockup.html` | Static before/after mockup with an inline "how it works" write-up. |
| `prototype.html` | **Fully interactive** prototype. Toggle columns, reset, reload — persistence works via `localStorage` as a stand-in for the API. |
| `plan.md` | Step-by-step development plan (registry → API → hook → picker → tests → flag flip). |
| `validation.md` | Acceptance criteria, unit tests, API tests, E2E tests, manual smoke, rollout & rollback. |

---

## TL;DR

- Add a **"Columns"** popover in the task-table toolbar. Checkbox per column.
- Two columns (`#`, `Title`) are locked-on so a row never loses identity.
- Persist selection to a per-user preference row keyed `tasks.table.columns`.
- No row → server returns `404` → client falls back to `DEFAULT_VISIBLE`.
- **"Reset to defaults"** deletes the row.
- Ships behind `tasks.customColumns` flag. Two PRs, ~9h focused work.

---

## Why this shape

### Registry as single source of truth

One `TASK_COLUMN_DEFS` array in the frontend defines every column's `id`, `label`, `accessor`, `defaultVisible`, `lockable`. Every consumer (the table, the picker, the validator, tests) reads from it. Retiring a column becomes a one-line change; forward compat is trivial because unknown IDs in stored payloads get silently dropped.

### Preference payload shape

```json
{
  "version": 1,
  "visible": ["id", "title", "status", "priority", "category", "dueDate", "updatedAt"],
  "order":   ["id", "title", "status", "priority", "category", "dueDate", "updatedAt"],
  "widths":  {}
}
```

- `version` lets us reshape later without breaking old clients.
- `order` is a superset of `visible` — reserved for the reorder-drag UI that ships in v1.1 (drag handles are already in the mockup for review, but not wired in v1).
- `widths` is reserved for column-resize persistence. No UI yet; harmless empty object.

### Locked-on columns

`id` and `title` are marked `lockable: true`. The picker disables their checkboxes and shows a 🔒 marker. Server-side, if a `PUT` arrives without them, we inject them before persisting — belt-and-braces so a scripted client can't create an unusable table.

### Debounced writes

Toggles feel instant (optimistic local state update) and collapse into one `PUT` after 500ms of quiet. No thrash when a user checks/unchecks a few columns in a row.

### Feature flag

`tasks.customColumns`:
- **off** → no "Columns" button, fixed layout (same as today).
- **on** → picker visible, preference honored.

Rollout: staff → 10% → 100%. Rollback is a single flag flip; stored rows remain harmless.

---

## API contract

```
GET    /api/preferences/tasks.table.columns   → 200 { version, visible, order, widths }
                                              → 404 (no row; client uses DEFAULT_VISIBLE)
                                              → 401 (unauthenticated)

PUT    /api/preferences/tasks.table.columns   → 200 (upserted)
                                              → 400 EMPTY_VISIBLE
                                              → 400 VERSION_MISMATCH

DELETE /api/preferences/tasks.table.columns   → 204 (idempotent — even if no row)
```

Server-side, after Zod validation:

1. Strip unknown column ids (forward compat).
2. Inject `LOCKED_ON` ids into `visible` if missing.
3. If `visible` is empty after stripping → reject with `400 EMPTY_VISIBLE`.
4. If `version !== 1` → reject.

---

## Frontend structure

```
src/features/tasks/table/
├── columnDefs.ts          # TASK_COLUMN_DEFS, DEFAULT_VISIBLE, LOCKED_ON
├── useTableColumns.ts     # load / toggle / reset hook + debounced PUT
├── ColumnPicker.tsx       # popover
├── TaskTable.tsx          # refactored to read from registry
└── __tests__/
    ├── columnDefs.test.ts
    ├── useTableColumns.test.ts
    └── ColumnPicker.test.tsx
```

The picker mounts in the toolbar next to Filter/Sort using whatever popover primitive Filter uses, so it inherits outside-click, Escape, and keyboard-nav behavior for free.

---

## Trade-offs & explicit non-goals (v1)

| Decision | Alternative considered | Why we chose this |
|---|---|---|
| One shared column set for the task table | Per-view (Backlog / Today / Board) | Keeps v1 small. Namespace design (`tasks.<surface>.table.columns`) leaves room to split later without a migration. |
| Server-side persistence | `localStorage` only | User asked for cross-device sync. Server-side write also lets us reset for a user via the DB during support. |
| Visibility only (no reorder) | Ship reorder in v1 | The picker gains a drag-and-drop story; not worth blocking visibility on it. Registry already exposes `order` array for v1.1. |
| Two locked-on columns | Fully user-controlled | Empty table is a support nightmare. `#` + `Title` gives every row an identity. |
| Silent drop of unknown IDs | Reject-and-migrate | Retiring a column shouldn't 500 the API. Silent drop = zero-downtime column retirements. |

---

## What "done" looks like

See `validation.md` for the exhaustive list. Highlights:

- Fresh user with no preference row → sees `DEFAULT_VISIBLE`, no flash.
- Toggle a column → hides immediately → reload → still hidden.
- Rapid toggles → exactly one `PUT` after 500ms.
- Locked-on rows → disabled checkbox + lock icon, no network call on click.
- Reset → `DELETE` fires, table snaps to defaults, subsequent `GET` returns 404.
- Feature flag off → picker not rendered, legacy fixed layout intact.
- Retired column id in stored row → dropped silently, table still renders.

---

## Sequencing

**PR 1 (~4h):** column registry, refactored `TaskTable` reading from registry, API endpoints + Zod validation, API tests. Flag stays off.

**PR 2 (~5h):** `useTableColumns` hook, `ColumnPicker`, wire into task-details page, unit + E2E tests. Flag stays off.

**Flag flip (~30m):** enable for staff, soak one week, ramp to 100%.

---

## Open questions worth flagging to the PM before PR 1

1. Column reordering in v1, or hold for v1.1? _(Proposal: v1.1.)_
2. Per-view preferences (Backlog vs. Today)? _(Proposal: one shared set now; namespaced key preserves the option.)_
3. Should reset require confirmation? _(Proposal: no — it's non-destructive; the underlying tasks don't change.)_

None of these block the PR-1 work — column registry + API contract are the same either way.

<!-- auto-generated plan — Snapshot from approved Run-Away draft; edit freely, your changes are preserved and used by the next run -->

# Plan — Selectable task-table columns, persisted in user preferences

**Task:** #2298 · Task details: selectable table fields, persisted in user preferences
**Goal:** Let each user pick which columns show up in the task table on the task details page. Persist per-user. Fall back to a sensible default. Provide a reset affordance.
**Feature flag:** `tasks.customColumns` (server + client), off by default until step 8.

---

## Scope

**In scope**
- Column visibility toggle (show/hide) on the task table.
- Persistence keyed to the current user.
- Default column set when no preference exists.
- "Reset to defaults" action.
- Two locked-on columns: `id` (`#`) and `title` (row identity).

**Out of scope (deferred / follow-ups)**
- Column reordering via drag (leave hooks in the data model; UI in v1.1).
- Column width persistence (schema slot reserved; no UI yet).
- Per-view preferences (Backlog vs Today vs Board). v1 ships one shared set for the task table surface.
- Filtering/sorting UX changes.

---

## Architecture at a glance

```
UserPreference (existing)
  key   = "tasks.table.columns"
  value = { version, visible[], order[], widths{} }

GET / PUT / DELETE  /api/preferences/tasks.table.columns
                            │
                            ▼
     useTableColumns() hook  ──►  <ColumnPicker/>  ──►  <TaskTable/>
                            │
                            ▼
                TASK_COLUMN_DEFS (single source of truth)
```

---

## Steps

### 1 · Column registry (frontend, ~1h)
Create `src/features/tasks/table/columnDefs.ts` exporting `TASK_COLUMN_DEFS`:

```ts
export type TaskColumnId =
  | "id" | "title" | "status" | "priority" | "category"
  | "assignee" | "dueDate" | "estimatedHours" | "actualHours"
  | "updatedAt" | "createdAt" | "objective" | "repository" | "tags";

export interface TaskColumnDef {
  id: TaskColumnId;
  label: string;
  accessor: (t: Task) => React.ReactNode;
  defaultVisible: boolean;
  lockable: boolean; // if true, cannot be hidden
}

export const TASK_COLUMN_DEFS: readonly TaskColumnDef[] = [ ... ];
export const DEFAULT_VISIBLE: TaskColumnId[] =
  TASK_COLUMN_DEFS.filter(c => c.defaultVisible).map(c => c.id);
export const LOCKED_ON: TaskColumnId[] = ["id", "title"];
```

Refactor the existing `<TaskTable/>` to render headers/cells from this registry rather than a hand-rolled JSX list.

### 2 · Server preference endpoints (~2h)
Namespaced key = `tasks.table.columns`. Three endpoints:

- `GET  /api/preferences/tasks.table.columns` → `{ version, visible, order, widths }` or `404`.
- `PUT  /api/preferences/tasks.table.columns` — validates payload (see step 3) and upserts.
- `DELETE /api/preferences/tasks.table.columns` — removes the row (client will refetch default).

Use whatever preference store is already there (Prisma `UserPreference` model or JSONB blob on `User`). Do **not** invent a new table if one exists.

### 3 · Payload validation (~30m, shared)
Zod schema in a shared module:

```ts
export const TaskColumnsPref = z.object({
  version: z.literal(1),
  visible: z.array(z.string()).min(1),           // must include locked-on
  order:   z.array(z.string()),                   // superset of visible
  widths:  z.record(z.string(), z.number().positive()).default({}),
});
```

Server-side, after parsing:
- Strip unknown column ids (forward compat when a column is retired).
- Force locked-on ids into `visible`.
- Reject if `visible` is empty after stripping → `400`.

### 4 · `useTableColumns()` hook (~1h)
- On mount: `GET` preference. If 404, use `DEFAULT_VISIBLE`.
- Exposes `{ visible, toggle(id), reset(), isLoaded }`.
- `toggle` optimistically updates local state, then **debounced 500ms** `PUT`.
- `reset` calls `DELETE` and revalidates.
- Locked-on ids ignore `toggle`.

### 5 · `<ColumnPicker/>` popover (~2h)
- Mounts in the task-table toolbar next to Filter/Sort.
- Renders one row per entry in `TASK_COLUMN_DEFS`, checkbox from `visible`.
- Locked-on rows show a small lock icon and disabled checkbox.
- Footer: "N of M visible" + "Reset to defaults" link.
- Popover closes on outside click / Escape.
- Uses existing popover primitive (whatever the Filter button uses).

### 6 · Wire it into the table page (~30m)
- Task details page renders `<TaskTable columns={visible} />`.
- `<TaskTable/>` reads `TASK_COLUMN_DEFS`, filters to `visible`, renders in registry order (reorder UI comes later).
- Skeleton row shown while `isLoaded === false` so we don't flash the default columns then swap.

### 7 · Tests (~2h)
- **Unit** — `columnDefs` registry integrity (all locked-on are `defaultVisible: true`); `useTableColumns` reducer paths (load, toggle, locked-on ignored, reset).
- **API** — happy PUT, empty-visible → 400, unknown id stripped, DELETE returns 204.
- **E2E** (Playwright) — see `validation.md` §E2E.

### 8 · Flag flip & polish (~30m)
- Enable `tasks.customColumns` for staff, then all users.
- Remove dead code paths that assumed fixed columns.
- Update the task-table docs page (screenshot the picker).

---

## Sequencing

Steps 1–3 can land in one PR (registry + endpoints + validation). Steps 4–6 land in a second PR (hook + picker + wiring). Step 7 tests can go alongside each PR. Step 8 is a small follow-up.

Estimated total: **~9h** of focused work, spread over 2 PRs.

---

## Risks / notes

- **Preference bloat** — if we later ship per-view preferences, key scheme becomes `tasks.<surface>.table.columns`. Design the server endpoint to accept the key as a path param from the start (`/api/preferences/:key`) if that's easy; otherwise refactor later.
- **Locked-on drift** — someone will inevitably want to hide `Title`. Explicit `lockable` flag in the registry + a comment explaining why.
- **Perf** — table already renders 128+ rows; hiding columns is pure JSX omission, no query changes needed.


---

## Acceptance criteria — your output is judged against this

# Validation — Selectable task-table columns

Companion to `plan.md`. This is how we prove the feature works before flipping the flag on for everyone.

---

## Acceptance criteria

- [ ] **AC-1** A "Columns" button appears in the task-table toolbar for users with `tasks.customColumns` enabled.
- [ ] **AC-2** Clicking it opens a popover listing every column defined in `TASK_COLUMN_DEFS`.
- [ ] **AC-3** Toggling a checkbox immediately shows/hides that column in the table.
- [ ] **AC-4** After a full page reload, the selection is preserved.
- [ ] **AC-5** After logging out and back in on another device, the selection is preserved.
- [ ] **AC-6** `id` (`#`) and `title` columns are always visible and cannot be toggled off (checkbox disabled + lock icon).
- [ ] **AC-7** Clicking "Reset to defaults" restores the `DEFAULT_VISIBLE` set immediately.
- [ ] **AC-8** A brand-new user (no preference row) sees `DEFAULT_VISIBLE` on first load — never a flash of the full 14-column set.
- [ ] **AC-9** If a stored column id no longer exists in `TASK_COLUMN_DEFS` (e.g. a retired column), it is silently ignored; the table still renders.
- [ ] **AC-10** With the feature flag OFF, the Columns button is not rendered and the table falls back to the current fixed layout.

---

## Unit tests

Located next to the code they test.

### `columnDefs.test.ts`
- Every `LOCKED_ON` id exists in `TASK_COLUMN_DEFS`.
- Every `LOCKED_ON` id has `defaultVisible: true` and `lockable: true`.
- No duplicate `id`s in the registry.
- `DEFAULT_VISIBLE` is a subset of the registry ids.

### `useTableColumns.test.ts`
- Initial `GET` 404 → hook exposes `DEFAULT_VISIBLE`, `isLoaded: true`.
- Initial `GET` 200 → hook exposes stored `visible`.
- `toggle("status")` when currently visible → removes it, fires debounced `PUT`.
- `toggle("id")` (locked-on) → no-op, no `PUT`.
- `reset()` → fires `DELETE`, then refetches, then exposes `DEFAULT_VISIBLE`.
- Rapid toggles collapse into a single `PUT` after 500ms.

### API tests (`preferences.tasks.table.columns.spec.ts`)
| Case | Request | Expected |
|---|---|---|
| Unauthenticated | `GET` without session | `401` |
| No stored row | `GET` | `404` |
| Happy PUT | `PUT { version:1, visible:["id","title","status"], order:[...], widths:{} }` | `200`, row persisted |
| Empty `visible` after strip | `PUT { visible: [] }` | `400` with `code: "EMPTY_VISIBLE"` |
| Unknown id stripped | `PUT { visible: ["id","title","ghost"] }` | `200`, stored value has no `ghost` |
| Locked-on missing | `PUT { visible: ["status"] }` | `200`, server injects `id` + `title` |
| Wrong version | `PUT { version: 2, ... }` | `400` |
| DELETE existing | `DELETE` | `204`, subsequent `GET` returns `404` |
| DELETE missing | `DELETE` when no row | `204` (idempotent) |

---

## E2E tests (Playwright)

Fixture: fresh user with no `tasks.table.columns` preference row.

### `column-picker.spec.ts`

1. **Default state**
   - Navigate to `/tasks`. Assert exactly the columns in `DEFAULT_VISIBLE` are visible in the `<thead>`.

2. **Toggle and persist**
   - Open "Columns" popover.
   - Uncheck **Assignee**. Assert its column disappears within 100ms.
   - Reload the page. Assert **Assignee** column still hidden.
   - Network log: exactly one `PUT /api/preferences/tasks.table.columns` between toggle and reload.

3. **Locked-on**
   - Open popover. Assert **#** and **Title** rows show a lock icon and disabled checkbox.
   - Attempt to click **Title**'s checkbox. Assert no network call and no visual change.

4. **Reset**
   - Hide 3 columns.
   - Click "Reset to defaults". Assert all `DEFAULT_VISIBLE` columns reappear.
   - Reload. Assert defaults still shown (i.e. server row deleted, not just client state).

5. **Cross-tab sync**
   - Open two tabs on `/tasks`.
   - In tab A: hide **Priority**.
   - In tab B: reload. Assert **Priority** hidden.

6. **Forward-compat**
   - Seed preference row with `visible: ["id","title","status","retired_column"]`.
   - Load `/tasks`. Assert table renders (id/title/status columns), no console errors, no crash.

7. **Feature flag off**
   - Disable `tasks.customColumns` for the fixture user.
   - Load `/tasks`. Assert no "Columns" button in the toolbar; assert legacy 10-column layout.

---

## Manual smoke checklist (pre-flag-flip)

Run through this on staging before enabling for all users.

- [ ] Toggle each of the 14 columns individually; every combination renders without layout jumps.
- [ ] Popover closes on outside click, on Escape, and on toolbar-button re-click.
- [ ] Popover is keyboard-navigable (Tab through checkboxes, Space to toggle, Enter on Reset).
- [ ] `aria-label` on the Columns button reads meaningfully to VoiceOver / NVDA.
- [ ] On 13" laptop (1440×900), horizontal scroll disappears when user trims to 6 columns.
- [ ] Dark mode + light mode both render the popover with correct contrast.
- [ ] Network tab: no thrash — rapid toggling produces at most 1 PUT per 500ms window.
- [ ] Delete preference row directly in DB → next load shows defaults, no error toast.

---

## Rollout & rollback

**Rollout**
1. Merge PR 1 (registry + API + validation). Flag stays off.
2. Merge PR 2 (hook + picker + wiring). Flag stays off.
3. Enable `tasks.customColumns` for staff (~1 week soak).
4. Enable for 10% of users.
5. Enable for 100%.

**Rollback**
- Flip `tasks.customColumns` off — the Columns button disappears, table reverts to the fixed layout. Stored preference rows remain intact (harmless).
- No DB migration to reverse.

---

## Metrics to watch (first week after full rollout)

- Distinct users with a stored `tasks.table.columns` preference row.
- Median number of visible columns per user (expect < 10; if ≥ 10 the picker isn't earning its keep).
- Error rate on `PUT /api/preferences/tasks.table.columns` (should be near zero; spikes = validation regression).
- Support tickets mentioning "columns" or "missing fields".

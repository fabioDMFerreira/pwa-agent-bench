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

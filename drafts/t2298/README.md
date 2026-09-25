# Draft — Task #2298 · Selectable task-table columns

This folder is the draft-mockup + proposal deliverable for PWA task **#2298**
("Task details: selectable table fields, persisted in user preferences").
It is not a working benchmark task; it lives under `drafts/` to keep the
main `bench/` directory untouched.

## Contents

| File | Purpose |
|---|---|
| `PROPOSAL.md` | Executive summary + design decisions. Read this first. |
| `plan.md` | Step-by-step development plan (registry → API → hook → picker → tests). |
| `validation.md` | Acceptance criteria + unit / API / E2E test matrix + rollout. |
| `mockup.html` | Static before/after mockup with an inline proposal narrative. |
| `prototype.html` | **Fully interactive** prototype — toggle columns, reset, reload; persistence via `localStorage` as an API stand-in. |

## How to review

1. Open `mockup.html` in a browser for the visual before/after.
2. Open `prototype.html` in a browser to interact with the working picker:
   - Toggle any column; watch the table update immediately.
   - Try to uncheck `#` or `Title` — the checkbox is disabled (locked-on).
   - Click **Reset to defaults** — the picker snaps back to `DEFAULT_VISIBLE`.
   - Reload the page — selections survive.
   - The bottom panels show the persisted payload and a live API call log.
3. Read `PROPOSAL.md` for the reasoning and trade-offs.
4. Read `plan.md` + `validation.md` for the execution plan.

## Not in v1 (see PROPOSAL.md for the full trade-off table)

- Column reordering via drag (drag-handles in the mockup are for v1.1).
- Column-width persistence (schema slot reserved as `widths: {}`; no UI).
- Per-view preferences (Backlog vs Today vs Board). Key scheme keeps the door open.

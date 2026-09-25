// TASK_COLUMN_DEFS — single source of truth for what the task table can render.
//
// Every consumer (the <TaskTable/>, the <ColumnPicker/>, the useTableColumns
// hook, and the server-side sanitizer) reads from this registry. Adding or
// retiring a column is a one-line change here; stored preferences that
// reference an unknown id are dropped silently by `sanitizeVisible()` for
// forward compatibility.

import type { ReactNode } from "react";
import type { Task } from "../types.js";

export type TaskColumnId =
  | "id"
  | "title"
  | "status"
  | "priority"
  | "category"
  | "assignee"
  | "dueDate"
  | "estimatedHours"
  | "actualHours"
  | "updatedAt"
  | "createdAt"
  | "objective"
  | "repository"
  | "tags";

export interface TaskColumnDef {
  id: TaskColumnId;
  label: string;
  accessor: (t: Task) => ReactNode;
  defaultVisible: boolean;
  /** If true, the column is always visible and cannot be hidden by the user. */
  lockable: boolean;
}

const fmtDate = (iso: string | null | undefined): string => {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toISOString().slice(0, 10);
};

const fmtHours = (n: number | null | undefined): string =>
  n == null ? "" : `${n}h`;

export const TASK_COLUMN_DEFS: readonly TaskColumnDef[] = [
  {
    id: "id",
    label: "#",
    defaultVisible: true,
    lockable: true,
    accessor: (t) => t.id,
  },
  {
    id: "title",
    label: "Title",
    defaultVisible: true,
    lockable: true,
    accessor: (t) => t.title,
  },
  {
    id: "status",
    label: "Status",
    defaultVisible: true,
    lockable: false,
    accessor: (t) => t.status,
  },
  {
    id: "priority",
    label: "Priority",
    defaultVisible: true,
    lockable: false,
    accessor: (t) => t.priority ?? "",
  },
  {
    id: "category",
    label: "Category",
    defaultVisible: true,
    lockable: false,
    accessor: (t) => t.category?.name ?? "",
  },
  {
    id: "assignee",
    label: "Assignee",
    defaultVisible: true,
    lockable: false,
    accessor: (t) => t.assignee?.name ?? "",
  },
  {
    id: "dueDate",
    label: "Due date",
    defaultVisible: true,
    lockable: false,
    accessor: (t) => fmtDate(t.dueDate),
  },
  {
    id: "estimatedHours",
    label: "Est. hours",
    defaultVisible: false,
    lockable: false,
    accessor: (t) => fmtHours(t.estimatedHours),
  },
  {
    id: "actualHours",
    label: "Actual hours",
    defaultVisible: false,
    lockable: false,
    accessor: (t) => fmtHours(t.actualHours),
  },
  {
    id: "updatedAt",
    label: "Updated",
    defaultVisible: true,
    lockable: false,
    accessor: (t) => fmtDate(t.updatedAt),
  },
  {
    id: "createdAt",
    label: "Created",
    defaultVisible: false,
    lockable: false,
    accessor: (t) => fmtDate(t.createdAt),
  },
  {
    id: "objective",
    label: "Objective",
    defaultVisible: false,
    lockable: false,
    accessor: (t) => t.objective?.title ?? "",
  },
  {
    id: "repository",
    label: "Repository",
    defaultVisible: false,
    lockable: false,
    accessor: (t) => t.repository?.name ?? "",
  },
  {
    id: "tags",
    label: "Tags",
    defaultVisible: false,
    lockable: false,
    accessor: (t) => (t.tags ?? []).join(", "),
  },
] as const;

export const ALL_COLUMN_IDS: readonly TaskColumnId[] = TASK_COLUMN_DEFS.map(
  (c) => c.id,
);

export const DEFAULT_VISIBLE: readonly TaskColumnId[] = TASK_COLUMN_DEFS.filter(
  (c) => c.defaultVisible,
).map((c) => c.id);

export const LOCKED_ON: readonly TaskColumnId[] = TASK_COLUMN_DEFS.filter(
  (c) => c.lockable,
).map((c) => c.id);

/**
 * Look up a column definition by id (returns undefined for retired columns
 * that may still linger in a stored preference row).
 */
export function findColumnDef(id: string): TaskColumnDef | undefined {
  return TASK_COLUMN_DEFS.find((c) => c.id === id);
}

/**
 * Clamp a raw list of column ids (possibly from a stored preference row) to
 * the current registry and force locked-on ids in. Used both server-side
 * (before persisting) and client-side (defence in depth).
 *
 * - Unknown ids are dropped.
 * - Duplicates are removed, preserving first-seen order.
 * - LOCKED_ON ids are appended if missing.
 * - Returns [] only when input is empty AND locked-on happens to be empty
 *   (never in production; LOCKED_ON always contains id + title).
 */
export function sanitizeVisible(raw: readonly string[]): TaskColumnId[] {
  const known = new Set(ALL_COLUMN_IDS);
  const seen = new Set<string>();
  const out: TaskColumnId[] = [];
  for (const id of raw) {
    if (!known.has(id as TaskColumnId)) continue;
    if (seen.has(id)) continue;
    seen.add(id);
    out.push(id as TaskColumnId);
  }
  for (const locked of LOCKED_ON) {
    if (!seen.has(locked)) {
      out.push(locked);
      seen.add(locked);
    }
  }
  return out;
}

/**
 * Return the visible list of column ids in canonical (registry) order.
 * Useful for the table header/body so users get a stable column order
 * regardless of the order they toggled things on.
 */
export function orderInRegistry(
  visible: readonly TaskColumnId[],
): TaskColumnId[] {
  const set = new Set(visible);
  return ALL_COLUMN_IDS.filter((id) => set.has(id));
}

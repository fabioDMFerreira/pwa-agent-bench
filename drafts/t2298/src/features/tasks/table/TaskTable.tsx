// Renders <table> using TASK_COLUMN_DEFS. The parent decides what's
// visible via the `columns` prop; TaskTable takes it, orders it against the
// registry, and renders headers + cells from the registry's accessors.

import {
  TASK_COLUMN_DEFS,
  orderInRegistry,
  type TaskColumnId,
} from "./columnDefs.js";
import type { Task } from "../types.js";

export interface TaskTableProps {
  tasks: readonly Task[];
  columns: readonly TaskColumnId[];
  isLoading?: boolean;
}

export function TaskTable({ tasks, columns, isLoading = false }: TaskTableProps) {
  if (isLoading) {
    return (
      <div data-testid="task-table-skeleton" style={{ padding: 24, color: "#9ca3af" }}>
        Loading table…
      </div>
    );
  }

  const ordered = orderInRegistry(columns);
  const defsById = new Map(TASK_COLUMN_DEFS.map((d) => [d.id, d]));

  return (
    <table data-testid="task-table" style={{ borderCollapse: "collapse", width: "100%" }}>
      <thead>
        <tr>
          {ordered.map((id) => {
            const def = defsById.get(id);
            if (!def) return null;
            return (
              <th
                key={id}
                data-column={id}
                style={{ borderBottom: "1px solid #e5e7eb", padding: "6px 10px", textAlign: "left", background: "#f9fafb" }}
              >
                {def.label}
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {tasks.map((task) => (
          <tr key={task.id} data-testid={`task-row-${task.id}`}>
            {ordered.map((id) => {
              const def = defsById.get(id);
              if (!def) return null;
              return (
                <td
                  key={id}
                  data-column={id}
                  style={{ borderBottom: "1px solid #e5e7eb", padding: "6px 10px" }}
                >
                  {def.accessor(task)}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

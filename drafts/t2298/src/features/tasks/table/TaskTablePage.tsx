// Wires <TaskTable/> to the useTableColumns() hook and to <ColumnPicker/>.
// This is the component the task-details route renders.

import { ColumnPicker } from "./ColumnPicker.js";
import { TaskTable } from "./TaskTable.js";
import { useTableColumns } from "./useTableColumns.js";
import type { Task } from "../types.js";

export interface TaskTablePageProps {
  tasks: readonly Task[];
  /** Wired to the `tasks.customColumns` feature flag. */
  columnPickerEnabled?: boolean;
}

export function TaskTablePage({
  tasks,
  columnPickerEnabled = true,
}: TaskTablePageProps) {
  const { visible, isLoaded, toggle, reset } = useTableColumns();

  return (
    <section>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginBottom: 8,
        }}
      >
        <h1 style={{ fontSize: 20, margin: 0 }}>Tasks</h1>
        <div style={{ flex: 1 }} />
        <button type="button" data-testid="filter-btn">
          Filter
        </button>
        <button type="button" data-testid="sort-btn">
          Sort
        </button>
        <ColumnPicker
          visible={visible}
          onToggle={toggle}
          onReset={reset}
          enabled={columnPickerEnabled}
        />
      </header>
      <TaskTable tasks={tasks} columns={visible} isLoading={!isLoaded} />
    </section>
  );
}

// Popover that lists every column in TASK_COLUMN_DEFS with a checkbox. The
// component is intentionally headless-ish: it takes `visible`, `onToggle`,
// and `onReset` and does not own any state. The consumer (TaskTablePage)
// wires it to useTableColumns().

import { useCallback, useEffect, useRef, useState } from "react";
import {
  LOCKED_ON,
  TASK_COLUMN_DEFS,
  type TaskColumnId,
} from "./columnDefs.js";

export interface ColumnPickerProps {
  visible: readonly TaskColumnId[];
  onToggle: (id: TaskColumnId) => void;
  onReset: () => void;
  /**
   * If false, the "Columns" button is not rendered. Wired to the
   * `tasks.customColumns` feature flag.
   */
  enabled?: boolean;
}

export function ColumnPicker({
  visible,
  onToggle,
  onReset,
  enabled = true,
}: ColumnPickerProps) {
  const [open, setOpen] = useState(false);
  const popRef = useRef<HTMLDivElement | null>(null);
  const btnRef = useRef<HTMLButtonElement | null>(null);
  const locked = new Set<TaskColumnId>(LOCKED_ON);

  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    const onClick = (e: MouseEvent) => {
      const target = e.target as Node | null;
      if (!target) return;
      if (popRef.current?.contains(target)) return;
      if (btnRef.current?.contains(target)) return;
      close();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("click", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("click", onClick);
    };
  }, [open, close]);

  if (!enabled) return null;

  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button
        ref={btnRef}
        type="button"
        aria-label="Choose visible columns"
        aria-expanded={open}
        data-testid="columns-btn"
        onClick={() => setOpen((v) => !v)}
      >
        Columns
      </button>
      {open && (
        <div
          ref={popRef}
          role="dialog"
          aria-label="Choose visible columns"
          data-testid="columns-popover"
          style={{
            position: "absolute",
            top: "100%",
            right: 0,
            marginTop: 4,
            background: "white",
            border: "1px solid #d1d5db",
            borderRadius: 8,
            padding: 12,
            minWidth: 240,
            boxShadow: "0 6px 16px rgba(0,0,0,0.12)",
            zIndex: 10,
          }}
        >
          {TASK_COLUMN_DEFS.map((def) => {
            const checked = visible.includes(def.id);
            const isLocked = locked.has(def.id);
            return (
              <label
                key={def.id}
                data-testid={`col-row-${def.id}`}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "4px 0",
                  color: isLocked ? "#6b7280" : undefined,
                }}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={isLocked}
                  aria-label={def.label}
                  data-testid={`col-checkbox-${def.id}`}
                  onChange={() => {
                    // Defence in depth: some test harnesses (fireEvent) fire
                    // change events even on disabled checkboxes. The hook
                    // already ignores locked-on toggles, but reject them
                    // here too so the click never even reaches it.
                    if (isLocked) return;
                    onToggle(def.id);
                  }}
                />
                <span>
                  {def.label}
                  {isLocked && (
                    <span
                      data-testid={`col-lock-${def.id}`}
                      aria-label="locked"
                      style={{ marginLeft: 6 }}
                    >
                      🔒
                    </span>
                  )}
                </span>
              </label>
            );
          })}
          <footer
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginTop: 8,
              paddingTop: 8,
              borderTop: "1px solid #e5e7eb",
              fontSize: 13,
            }}
          >
            <span data-testid="picker-count">
              {visible.length} of {TASK_COLUMN_DEFS.length} visible
            </span>
            <button
              type="button"
              data-testid="reset-btn"
              onClick={() => {
                onReset();
                close();
              }}
              style={{
                background: "none",
                border: "none",
                color: "#2563eb",
                cursor: "pointer",
                textDecoration: "underline",
                padding: 0,
                font: "inherit",
              }}
            >
              Reset to defaults
            </button>
          </footer>
        </div>
      )}
    </div>
  );
}

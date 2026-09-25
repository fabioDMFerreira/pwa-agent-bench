// Minimal Task model shared by the column registry, table, and hook.
// The real PWA Task is much larger; the registry only reads the fields
// listed below via typed accessors, so widening the model here is a
// non-breaking change downstream.

export interface Task {
  id: number;
  title: string;
  status:
    | "BACKLOG"
    | "TODO"
    | "BLOCKED"
    | "IN_PROGRESS"
    | "IN_REVIEW"
    | "IN_VERIFICATION"
    | "COMPLETED"
    | "CANCELLED";
  priority?: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "MINIMAL" | null;
  category?: { id: number; name: string } | null;
  assignee?: { id: number; name: string } | null;
  dueDate?: string | null;
  estimatedHours?: number | null;
  actualHours?: number | null;
  updatedAt?: string | null;
  createdAt?: string | null;
  objective?: { id: number; title: string } | null;
  repository?: { id: number; name: string } | null;
  tags?: string[] | null;
}

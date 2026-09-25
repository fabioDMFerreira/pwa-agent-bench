// In-memory preference store. The real PWA backs this with Prisma's
// UserPreference model (jsonb value keyed by (user_id, key)); the shape and
// semantics are identical to the store below so the router logic doesn't
// change when it's swapped in.

import type { TaskColumnsPref } from "../shared/schema.js";

export interface PreferenceStore {
  get(userId: string, key: string): TaskColumnsPref | undefined;
  set(userId: string, key: string, value: TaskColumnsPref): void;
  delete(userId: string, key: string): boolean;
  /** Test helper — wipes every row. */
  reset(): void;
}

export function createMemoryStore(): PreferenceStore {
  const rows = new Map<string, TaskColumnsPref>();
  const compose = (u: string, k: string) => `${u}::${k}`;
  return {
    get(userId, key) {
      return rows.get(compose(userId, key));
    },
    set(userId, key, value) {
      rows.set(compose(userId, key), value);
    },
    delete(userId, key) {
      return rows.delete(compose(userId, key));
    },
    reset() {
      rows.clear();
    },
  };
}

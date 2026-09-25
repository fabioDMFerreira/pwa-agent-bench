// React hook that owns the column-visibility preference for one user session.
//
// - On mount: GET the preference. 404 → fall back to DEFAULT_VISIBLE.
// - toggle(id): flip visibility for a non-locked column. Fires a debounced
//   PUT (500ms of quiet) so rapid checkbox flicks collapse into one write.
// - reset(): DELETE the row, revert local state to DEFAULT_VISIBLE.
// - Locked-on ids are silently ignored by toggle().

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  DEFAULT_VISIBLE,
  LOCKED_ON,
  sanitizeVisible,
  type TaskColumnId,
} from "./columnDefs.js";

const PREF_URL = "/api/preferences/tasks.table.columns";
const DEBOUNCE_MS = 500;
const CURRENT_VERSION = 1 as const;

export interface UseTableColumnsResult {
  visible: TaskColumnId[];
  isLoaded: boolean;
  toggle: (id: TaskColumnId) => void;
  reset: () => Promise<void>;
  /** For tests only — how many PUTs have been flushed. */
  __putCount: number;
}

export interface UseTableColumnsOptions {
  /** Injected for tests; defaults to the browser `fetch`. */
  fetchImpl?: typeof fetch;
  /** Injected for tests so debouncing can be advanced with fake timers. */
  debounceMs?: number;
  /** Called after the initial load resolves (test hook). */
  onReady?: (loaded: boolean) => void;
}

export function useTableColumns(
  options: UseTableColumnsOptions = {},
): UseTableColumnsResult {
  const debounceMs = options.debounceMs ?? DEBOUNCE_MS;
  const fetchImpl =
    options.fetchImpl ?? (globalThis.fetch.bind(globalThis) as typeof fetch);

  const [visible, setVisible] = useState<TaskColumnId[]>(() => [
    ...DEFAULT_VISIBLE,
  ]);
  const [isLoaded, setLoaded] = useState(false);
  const putCountRef = useRef(0);
  const pendingRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const currentVisibleRef = useRef(visible);
  currentVisibleRef.current = visible;

  const lockedSet = useMemo(() => new Set(LOCKED_ON), []);

  const flushPut = useCallback(
    async (payloadVisible: TaskColumnId[]) => {
      const clean = sanitizeVisible(payloadVisible);
      putCountRef.current += 1;
      await fetchImpl(PREF_URL, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          version: CURRENT_VERSION,
          visible: clean,
          order: clean,
          widths: {},
        }),
      }).catch(() => {
        // Swallow — the UI already reflects the desired state; the next
        // toggle will attempt another write. A production build would push
        // to a toast queue here.
      });
    },
    [fetchImpl],
  );

  const scheduleFlush = useCallback(() => {
    if (pendingRef.current) clearTimeout(pendingRef.current);
    pendingRef.current = setTimeout(() => {
      pendingRef.current = null;
      void flushPut(currentVisibleRef.current);
    }, debounceMs);
  }, [debounceMs, flushPut]);

  const toggle = useCallback(
    (id: TaskColumnId) => {
      if (lockedSet.has(id)) return; // locked-on: silent no-op
      setVisible((prev) => {
        const next = prev.includes(id)
          ? prev.filter((x) => x !== id)
          : [...prev, id];
        return sanitizeVisible(next);
      });
      scheduleFlush();
    },
    [lockedSet, scheduleFlush],
  );

  const reset = useCallback(async () => {
    if (pendingRef.current) {
      clearTimeout(pendingRef.current);
      pendingRef.current = null;
    }
    await fetchImpl(PREF_URL, { method: "DELETE" }).catch(() => undefined);
    setVisible([...DEFAULT_VISIBLE]);
  }, [fetchImpl]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetchImpl(PREF_URL, { method: "GET" });
        if (cancelled) return;
        if (res.status === 404) {
          setVisible([...DEFAULT_VISIBLE]);
        } else if (res.ok) {
          const body = (await res.json()) as {
            visible?: string[];
          };
          const clean = sanitizeVisible(body.visible ?? []);
          setVisible(clean.length > 0 ? clean : [...DEFAULT_VISIBLE]);
        } else {
          setVisible([...DEFAULT_VISIBLE]);
        }
      } catch {
        setVisible([...DEFAULT_VISIBLE]);
      } finally {
        if (!cancelled) {
          setLoaded(true);
          options.onReady?.(true);
        }
      }
    })();
    return () => {
      cancelled = true;
      if (pendingRef.current) clearTimeout(pendingRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchImpl]);

  return {
    visible,
    isLoaded,
    toggle,
    reset,
    __putCount: putCountRef.current,
  };
}

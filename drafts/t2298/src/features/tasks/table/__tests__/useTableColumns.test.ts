import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useTableColumns } from "../useTableColumns.js";
import { DEFAULT_VISIBLE } from "../columnDefs.js";

/**
 * Build a fake fetch: `queue` is checked in order; each entry is either a
 * response spec or a function returning one. Records every call in `calls`.
 */
interface FakeResponseSpec {
  status?: number;
  body?: string;
}

function makeFetch(
  responses: Array<FakeResponseSpec | ((init: RequestInit | undefined) => FakeResponseSpec)>,
) {
  const calls: Array<{ url: string; init: RequestInit | undefined }> = [];
  let i = 0;
  const impl: typeof fetch = async (input, init) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
        ? input.toString()
        : (input as Request).url;
    calls.push({ url, init });
    const spec = responses[i] ?? responses[responses.length - 1];
    i++;
    const resolved = typeof spec === "function" ? spec(init) : spec;
    const status = resolved.status ?? 200;
    const bodyText = resolved.body ?? "";
    return new Response(bodyText, {
      status,
      headers: { "content-type": "application/json" },
    });
  };
  return { fetch: impl, calls };
}

describe("useTableColumns() — initial load", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("GET 404 → hook exposes DEFAULT_VISIBLE with isLoaded true", async () => {
    const { fetch: f, calls } = makeFetch([{ status: 404 }]);
    const { result } = renderHook(() =>
      useTableColumns({ fetchImpl: f, debounceMs: 500 }),
    );
    await vi.waitFor(() => expect(result.current.isLoaded).toBe(true));
    expect(result.current.visible).toEqual([...DEFAULT_VISIBLE]);
    expect(calls[0]?.init?.method).toBe("GET");
  });

  it("GET 200 → hook exposes stored visible list", async () => {
    const stored = JSON.stringify({
      version: 1,
      visible: ["id", "title", "status", "priority"],
      order: ["id", "title", "status", "priority"],
      widths: {},
    });
    const { fetch: f } = makeFetch([{ status: 200, body: stored }]);
    const { result } = renderHook(() =>
      useTableColumns({ fetchImpl: f, debounceMs: 500 }),
    );
    await vi.waitFor(() => expect(result.current.isLoaded).toBe(true));
    expect(result.current.visible).toEqual(["id", "title", "status", "priority"]);
  });

  it("GET 200 with retired column id → silently strips it", async () => {
    const stored = JSON.stringify({
      version: 1,
      visible: ["id", "title", "status", "retired_column"],
      order: [],
      widths: {},
    });
    const { fetch: f } = makeFetch([{ status: 200, body: stored }]);
    const { result } = renderHook(() =>
      useTableColumns({ fetchImpl: f, debounceMs: 500 }),
    );
    await vi.waitFor(() => expect(result.current.isLoaded).toBe(true));
    expect(result.current.visible).not.toContain("retired_column");
    expect(result.current.visible).toContain("id");
    expect(result.current.visible).toContain("title");
    expect(result.current.visible).toContain("status");
  });
});

describe("useTableColumns() — toggle & debounce", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("toggle('status') when currently visible → removes it, fires debounced PUT", async () => {
    const { fetch: f, calls } = makeFetch([
      { status: 404 }, // GET
      { status: 200, body: "{}" }, // PUT
    ]);
    const { result } = renderHook(() =>
      useTableColumns({ fetchImpl: f, debounceMs: 500 }),
    );
    await vi.waitFor(() => expect(result.current.isLoaded).toBe(true));

    act(() => result.current.toggle("status"));
    expect(result.current.visible).not.toContain("status");

    // PUT hasn't fired yet — only the initial GET was made.
    expect(calls.filter((c) => c.init?.method === "PUT")).toHaveLength(0);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    const puts = calls.filter((c) => c.init?.method === "PUT");
    expect(puts).toHaveLength(1);
    const body = JSON.parse(String(puts[0].init!.body));
    expect(body.visible).not.toContain("status");
    expect(body.visible).toContain("id");
    expect(body.visible).toContain("title");
  });

  it("toggle('id') (locked-on) → no-op, no PUT", async () => {
    const { fetch: f, calls } = makeFetch([{ status: 404 }]);
    const { result } = renderHook(() =>
      useTableColumns({ fetchImpl: f, debounceMs: 500 }),
    );
    await vi.waitFor(() => expect(result.current.isLoaded).toBe(true));

    const before = [...result.current.visible];
    act(() => result.current.toggle("id"));
    expect(result.current.visible).toEqual(before);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(calls.filter((c) => c.init?.method === "PUT")).toHaveLength(0);
  });

  it("rapid toggles collapse into a single PUT after 500ms", async () => {
    const { fetch: f, calls } = makeFetch([{ status: 404 }, { status: 200, body: "{}" }]);
    const { result } = renderHook(() =>
      useTableColumns({ fetchImpl: f, debounceMs: 500 }),
    );
    await vi.waitFor(() => expect(result.current.isLoaded).toBe(true));

    act(() => result.current.toggle("status"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    act(() => result.current.toggle("priority"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    act(() => result.current.toggle("assignee"));

    // Nothing should have flushed yet.
    expect(calls.filter((c) => c.init?.method === "PUT")).toHaveLength(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(calls.filter((c) => c.init?.method === "PUT")).toHaveLength(1);
  });
});

describe("useTableColumns() — reset", () => {
  it("reset() fires DELETE then exposes DEFAULT_VISIBLE", async () => {
    const stored = JSON.stringify({
      version: 1,
      visible: ["id", "title", "status"],
      order: [],
      widths: {},
    });
    const { fetch: f, calls } = makeFetch([
      { status: 200, body: stored }, // GET
      { status: 204 }, // DELETE
    ]);
    const { result } = renderHook(() => useTableColumns({ fetchImpl: f }));
    await waitFor(() => expect(result.current.isLoaded).toBe(true));
    expect(result.current.visible).toEqual(["id", "title", "status"]);

    await act(async () => {
      await result.current.reset();
    });
    expect(result.current.visible).toEqual([...DEFAULT_VISIBLE]);
    expect(calls.some((c) => c.init?.method === "DELETE")).toBe(true);
  });
});

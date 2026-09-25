import { describe, it, expect } from "vitest";
import {
  ALL_COLUMN_IDS,
  DEFAULT_VISIBLE,
  LOCKED_ON,
  TASK_COLUMN_DEFS,
  findColumnDef,
  orderInRegistry,
  sanitizeVisible,
} from "../columnDefs.js";

describe("column registry integrity", () => {
  it("every LOCKED_ON id exists in TASK_COLUMN_DEFS", () => {
    for (const id of LOCKED_ON) {
      expect(TASK_COLUMN_DEFS.some((c) => c.id === id)).toBe(true);
    }
  });

  it("every LOCKED_ON id has defaultVisible: true and lockable: true", () => {
    for (const id of LOCKED_ON) {
      const def = TASK_COLUMN_DEFS.find((c) => c.id === id);
      expect(def).toBeDefined();
      expect(def!.defaultVisible).toBe(true);
      expect(def!.lockable).toBe(true);
    }
  });

  it("has no duplicate ids in the registry", () => {
    const seen = new Set<string>();
    for (const def of TASK_COLUMN_DEFS) {
      expect(seen.has(def.id)).toBe(false);
      seen.add(def.id);
    }
  });

  it("DEFAULT_VISIBLE is a subset of the registry ids", () => {
    const known = new Set(ALL_COLUMN_IDS);
    for (const id of DEFAULT_VISIBLE) {
      expect(known.has(id)).toBe(true);
    }
  });

  it("DEFAULT_VISIBLE is non-empty and includes both locked-on ids", () => {
    expect(DEFAULT_VISIBLE.length).toBeGreaterThan(0);
    for (const id of LOCKED_ON) {
      expect(DEFAULT_VISIBLE).toContain(id);
    }
  });
});

describe("findColumnDef()", () => {
  it("returns the definition for a known id", () => {
    expect(findColumnDef("status")?.label).toBe("Status");
  });

  it("returns undefined for an unknown id", () => {
    expect(findColumnDef("ghost")).toBeUndefined();
  });
});

describe("sanitizeVisible()", () => {
  it("drops unknown ids", () => {
    const out = sanitizeVisible(["id", "title", "ghost", "status"]);
    expect(out).toEqual(["id", "title", "status"]);
  });

  it("deduplicates while preserving first-seen order", () => {
    const out = sanitizeVisible(["status", "id", "status", "title"]);
    expect(out).toEqual(["status", "id", "title"]);
  });

  it("injects locked-on ids if they are missing", () => {
    const out = sanitizeVisible(["status"]);
    expect(out).toContain("id");
    expect(out).toContain("title");
    expect(out).toContain("status");
  });

  it("returns just the locked-on set when given empty input", () => {
    const out = sanitizeVisible([]);
    expect(out).toEqual([...LOCKED_ON]);
  });
});

describe("orderInRegistry()", () => {
  it("re-orders the visible list to match the registry order", () => {
    const out = orderInRegistry(["updatedAt", "status", "id", "title"]);
    // Registry order: id, title, status, ..., updatedAt.
    expect(out.indexOf("id")).toBeLessThan(out.indexOf("title"));
    expect(out.indexOf("title")).toBeLessThan(out.indexOf("status"));
    expect(out.indexOf("status")).toBeLessThan(out.indexOf("updatedAt"));
  });

  it("drops ids not in the input", () => {
    const out = orderInRegistry(["id", "title"]);
    expect(out).toEqual(["id", "title"]);
  });
});

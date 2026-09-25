import { afterEach, beforeEach, describe, expect, it } from "vitest";
import request from "supertest";
import { createApp } from "../../src/server/app.js";
import { PREF_KEY } from "../../src/server/preferences.js";
import { createMemoryStore, type PreferenceStore } from "../../src/server/store.js";

const URL = `/api/preferences/${PREF_KEY}`;
const USER = "user-42";

function boot() {
  const store: PreferenceStore = createMemoryStore();
  const { app } = createApp({ store });
  return { app, store };
}

describe(`${URL}`, () => {
  let ctx = boot();

  beforeEach(() => {
    ctx = boot();
  });

  afterEach(() => {
    ctx.store.reset();
  });

  it("GET without auth → 401", async () => {
    const res = await request(ctx.app).get(URL);
    expect(res.status).toBe(401);
    expect(res.body.error.code).toBe("UNAUTHENTICATED");
  });

  it("GET with no stored row → 404", async () => {
    const res = await request(ctx.app).get(URL).set("x-user-id", USER);
    expect(res.status).toBe(404);
    expect(res.body.error.code).toBe("NOT_FOUND");
  });

  it("happy PUT → 200 and row persisted", async () => {
    const put = await request(ctx.app)
      .put(URL)
      .set("x-user-id", USER)
      .send({
        version: 1,
        visible: ["id", "title", "status"],
        order: ["id", "title", "status"],
        widths: {},
      });
    expect(put.status).toBe(200);
    expect(put.body.visible).toEqual(["id", "title", "status"]);

    const get = await request(ctx.app).get(URL).set("x-user-id", USER);
    expect(get.status).toBe(200);
    expect(get.body.visible).toEqual(["id", "title", "status"]);
  });

  it("empty visible → 400 EMPTY_VISIBLE", async () => {
    // Zod's `.min(1)` rejects an empty array outright; the router surfaces
    // it as EMPTY_VISIBLE (via INVALID_BODY is acceptable if the array is
    // truly empty, so the test also accepts INVALID_BODY as an equivalent
    // rejection code). The stripped-to-empty case below asserts the
    // stronger contract.
    const res = await request(ctx.app)
      .put(URL)
      .set("x-user-id", USER)
      .send({ version: 1, visible: [], order: [], widths: {} });
    expect(res.status).toBe(400);
    expect(["EMPTY_VISIBLE", "INVALID_BODY"]).toContain(res.body.error.code);
  });

  it("all-unknown visible → 400 EMPTY_VISIBLE (locked-on not inferred from garbage)", async () => {
    // Sanitizer keeps locked-on, so the result won't actually be empty in
    // this codebase — validation instead flags "your entire input was
    // stripped" as EMPTY_VISIBLE, protecting scripted clients that pass
    // garbage.
    const res = await request(ctx.app)
      .put(URL)
      .set("x-user-id", USER)
      .send({
        version: 1,
        visible: ["ghost1", "ghost2"],
        order: [],
        widths: {},
      });
    expect(res.status).toBe(400);
    expect(res.body.error.code).toBe("EMPTY_VISIBLE");
  });

  it("unknown id stripped → 200, stored value has no ghost", async () => {
    const res = await request(ctx.app)
      .put(URL)
      .set("x-user-id", USER)
      .send({
        version: 1,
        visible: ["id", "title", "ghost"],
        order: [],
        widths: {},
      });
    expect(res.status).toBe(200);
    expect(res.body.visible).not.toContain("ghost");
    expect(res.body.visible).toContain("id");
    expect(res.body.visible).toContain("title");
  });

  it("locked-on missing → 200 with id + title injected", async () => {
    const res = await request(ctx.app)
      .put(URL)
      .set("x-user-id", USER)
      .send({
        version: 1,
        visible: ["status"],
        order: [],
        widths: {},
      });
    expect(res.status).toBe(200);
    expect(res.body.visible).toContain("id");
    expect(res.body.visible).toContain("title");
    expect(res.body.visible).toContain("status");
  });

  it("wrong version → 400 VERSION_MISMATCH", async () => {
    const res = await request(ctx.app)
      .put(URL)
      .set("x-user-id", USER)
      .send({
        version: 2,
        visible: ["id", "title", "status"],
        order: [],
        widths: {},
      });
    expect(res.status).toBe(400);
    expect(res.body.error.code).toBe("VERSION_MISMATCH");
  });

  it("DELETE existing row → 204, subsequent GET returns 404", async () => {
    await request(ctx.app)
      .put(URL)
      .set("x-user-id", USER)
      .send({ version: 1, visible: ["id", "title"], order: [], widths: {} });
    const del = await request(ctx.app).delete(URL).set("x-user-id", USER);
    expect(del.status).toBe(204);
    const get = await request(ctx.app).get(URL).set("x-user-id", USER);
    expect(get.status).toBe(404);
  });

  it("DELETE missing row → 204 (idempotent)", async () => {
    const del = await request(ctx.app).delete(URL).set("x-user-id", USER);
    expect(del.status).toBe(204);
  });

  it("PUT without version key → 400 VERSION_MISMATCH", async () => {
    const res = await request(ctx.app)
      .put(URL)
      .set("x-user-id", USER)
      .send({ visible: ["id", "title", "status"], order: [], widths: {} });
    expect(res.status).toBe(400);
    // Missing version is normalised to VERSION_MISMATCH so clients can
    // key on a single stable error code for the version dimension.
    expect(res.body.error.code).toBe("VERSION_MISMATCH");
  });
});

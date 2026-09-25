import { expect, test } from "@playwright/test";

// Fresh user for each spec so a leftover preference row from one test can't
// leak into another. The demo page reads `?user=` and sets it in the
// x-demo-user header on every API call.
function userIdFor(name: string): string {
  return `pw-${name}-${Math.random().toString(36).slice(2, 8)}`;
}

async function seedPreference(
  request: import("@playwright/test").APIRequestContext,
  user: string,
  visible: string[],
) {
  await request.put("/api/preferences/tasks.table.columns", {
    headers: { "x-user-id": user, "content-type": "application/json" },
    data: {
      version: 1,
      visible,
      order: visible,
      widths: {},
    },
  });
}

async function deletePreference(
  request: import("@playwright/test").APIRequestContext,
  user: string,
) {
  await request.delete("/api/preferences/tasks.table.columns", {
    headers: { "x-user-id": user },
  });
}

async function setFlag(
  request: import("@playwright/test").APIRequestContext,
  enabled: boolean,
) {
  await request.put("/api/flags/tasks.customColumns", {
    data: { enabled },
    headers: { "content-type": "application/json" },
  });
}

const DEFAULT_VISIBLE = [
  "id",
  "title",
  "status",
  "priority",
  "category",
  "assignee",
  "dueDate",
  "updatedAt",
];

test.beforeEach(async ({ request }) => {
  await setFlag(request, true);
});

test("1. Default state — brand-new user sees DEFAULT_VISIBLE", async ({ page }) => {
  const user = userIdFor("default");
  await page.goto(`/demo/tasks?user=${user}`);
  await page.waitForSelector('[data-loaded="true"]');
  const headers = await page.locator("#task-thead th").evaluateAll((els) =>
    els.map((e) => e.getAttribute("data-column")),
  );
  expect(headers).toEqual(DEFAULT_VISIBLE);
});

test("2. Toggle and persist — hiding Assignee survives reload with one PUT", async ({
  page,
  request,
}) => {
  const user = userIdFor("toggle");
  await page.goto(`/demo/tasks?user=${user}`);
  await page.waitForSelector('[data-loaded="true"]');

  const puts: string[] = [];
  page.on("request", (req) => {
    if (
      req.method() === "PUT" &&
      req.url().includes("/api/preferences/tasks.table.columns")
    ) {
      puts.push(req.url());
    }
  });

  await page.getByTestId("columns-btn").click();
  await page.getByTestId("col-checkbox-assignee").click();
  await expect(page.locator('#task-thead th[data-column="assignee"]')).toHaveCount(0);

  // Wait past the 500 ms debounce, then verify exactly one PUT flushed.
  await page.waitForTimeout(700);
  expect(puts.length).toBe(1);

  await page.reload();
  await page.waitForSelector('[data-loaded="true"]');
  await expect(page.locator('#task-thead th[data-column="assignee"]')).toHaveCount(0);
});

test("3. Locked-on — # and Title show a lock icon with disabled checkbox", async ({
  page,
}) => {
  const user = userIdFor("locked");
  await page.goto(`/demo/tasks?user=${user}`);
  await page.waitForSelector('[data-loaded="true"]');
  await page.getByTestId("columns-btn").click();

  for (const id of ["id", "title"]) {
    const cb = page.getByTestId(`col-checkbox-${id}`);
    await expect(cb).toBeDisabled();
    await expect(cb).toBeChecked();
  }

  const before = await page.locator("#task-thead th").evaluateAll((els) =>
    els.map((e) => e.getAttribute("data-column")),
  );
  await page.getByTestId("col-checkbox-title").click({ force: true });
  const after = await page.locator("#task-thead th").evaluateAll((els) =>
    els.map((e) => e.getAttribute("data-column")),
  );
  expect(after).toEqual(before);
});

test("4. Reset — after hiding 3 columns, reset restores defaults & survives reload", async ({
  page,
}) => {
  const user = userIdFor("reset");
  await page.goto(`/demo/tasks?user=${user}`);
  await page.waitForSelector('[data-loaded="true"]');

  await page.getByTestId("columns-btn").click();
  await page.getByTestId("col-checkbox-priority").click();
  await page.getByTestId("col-checkbox-assignee").click();
  await page.getByTestId("col-checkbox-updatedAt").click();
  await page.waitForTimeout(700);

  await page.getByTestId("reset-btn").click();
  await page.waitForTimeout(200);
  const restored = await page.locator("#task-thead th").evaluateAll((els) =>
    els.map((e) => e.getAttribute("data-column")),
  );
  expect(restored).toEqual(DEFAULT_VISIBLE);

  await page.reload();
  await page.waitForSelector('[data-loaded="true"]');
  const afterReload = await page.locator("#task-thead th").evaluateAll((els) =>
    els.map((e) => e.getAttribute("data-column")),
  );
  expect(afterReload).toEqual(DEFAULT_VISIBLE);
});

test("5. Cross-tab sync — reload picks up other tab's change", async ({
  browser,
  request,
}) => {
  const user = userIdFor("crosstab");
  const ctxA = await browser.newContext();
  const ctxB = await browser.newContext();
  const pageA = await ctxA.newPage();
  const pageB = await ctxB.newPage();
  await pageA.goto(`/demo/tasks?user=${user}`);
  await pageB.goto(`/demo/tasks?user=${user}`);
  await pageA.waitForSelector('[data-loaded="true"]');
  await pageB.waitForSelector('[data-loaded="true"]');

  await pageA.getByTestId("columns-btn").click();
  await pageA.getByTestId("col-checkbox-priority").click();
  await pageA.waitForTimeout(700);

  await pageB.reload();
  await pageB.waitForSelector('[data-loaded="true"]');
  await expect(pageB.locator('#task-thead th[data-column="priority"]')).toHaveCount(0);

  await ctxA.close();
  await ctxB.close();
  await deletePreference(request, user);
});

test("6. Forward-compat — retired column id in stored row is dropped silently", async ({
  page,
  request,
}) => {
  const user = userIdFor("compat");
  await seedPreference(request, user, [
    "id",
    "title",
    "status",
    "retired_column",
  ]);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(`/demo/tasks?user=${user}`);
  await page.waitForSelector('[data-loaded="true"]');
  const headers = await page.locator("#task-thead th").evaluateAll((els) =>
    els.map((e) => e.getAttribute("data-column")),
  );
  expect(headers).toEqual(["id", "title", "status"]);
  expect(errors).toHaveLength(0);
});

test("7. Feature flag off — no Columns button, table renders", async ({
  page,
  request,
}) => {
  await setFlag(request, false);
  const user = userIdFor("flag");
  await page.goto(`/demo/tasks?user=${user}`);
  await page.waitForSelector('[data-loaded="true"]');
  await expect(page.getByTestId("columns-btn")).toBeHidden();
  const headers = await page.locator("#task-thead th").evaluateAll((els) =>
    els.map((e) => e.getAttribute("data-column")),
  );
  expect(headers.length).toBeGreaterThan(0);
});

// Boot the reference server for the Playwright suite and for manual demos.
// `npm run serve` uses this entry via tsx.

import { createApp } from "./app.js";

const port = Number(process.env.PORT ?? 4318);
const { app } = createApp();

app.listen(port, () => {
  // eslint-disable-next-line no-console
  console.log(`[task-2298] listening on http://localhost:${port}`);
});

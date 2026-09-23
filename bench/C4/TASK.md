# C4 — Convert the fetch pipeline to async

Work only inside `bench/C4/`. Do not modify existing tests.

The pipeline in `src/` is synchronous and slow: every fetch blocks for
`fetchers.LATENCY` seconds and everything runs one call at a time.

Files involved:
- `src/fetchers.py` — `fetch_user`, `fetch_orders`, `fetch_summary`, plus
  `LATENCY` and the `UserNotFound` exception.
- `src/pipeline.py` — `run_pipeline(user_id)` and `run_many(user_ids)`.
- `src/cli.py` — `main(argv) -> int` entry point.

## Requirements

1. The three fetchers become `async def`. Simulated latency must be
   **non-blocking** (`await asyncio.sleep(LATENCY)`, reading the module-level
   `LATENCY` at call time). Return values and the `UserNotFound` behaviour are
   unchanged.
2. `run_pipeline` becomes `async def`. It fetches the user first, then runs
   `fetch_orders` and `fetch_summary` **concurrently** with `asyncio.gather`.
   Result shape is unchanged.
3. `run_many` becomes `async def` and runs all users' pipelines
   **concurrently**. Results stay in input order.
4. Errors propagate unchanged: if any fetch raises, `run_pipeline` /
   `run_many` raise that same exception (not wrapped, not swallowed, not
   turned into `None`).
5. `cli.main` drives the async code with `asyncio.run` and keeps its exact
   output format and exit codes (see its docstring).

**Deliverable:** updated `src/fetchers.py`, `src/pipeline.py`, `src/cli.py`;
tests pass with `cd bench/C4 && python3 -m pytest -q`.

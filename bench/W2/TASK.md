# W2 — Choose a retry library: tenacity vs backoff vs stamina

Work only inside `bench/W2/`. Do not modify any code. Use web research.

## Context

`ledger-sync` is an **asyncio** service (Python 3.12) that calls a flaky
partner HTTP API through `httpx.AsyncClient`. Today every call site has its
own hand-rolled `for attempt in range(3): ... await asyncio.sleep(1)` loop.
We want to replace these with one third-party retry library.

Requirements:

- R1. Retry `async def` functions; retry only on specific exceptions
  (`httpx.TransportError`, and `httpx.HTTPStatusError` for 5xx/429 only).
- R2. Exponential backoff **with jitter**, a cap on total attempts and on
  total time.
- R3. Tests must run fast: a supported way to disable/short-circuit retry
  waits in the test suite (not just monkeypatching `asyncio.sleep`).
- R4. Type hints shipped with the package (`py.typed`) — we run mypy --strict.
- R5. Licence policy: permissive only (MIT, BSD, Apache-2.0).
- R6. Maintenance policy: the project must not be archived/unmaintained and
  must have had a release within the last 12 months.

## Deliverable

Write `bench/W2/RESEARCH.md` with:

1. A comparison table of **tenacity**, **backoff** and **stamina**: latest
   release version + date, licence, repository status (active/archived),
   Python support, async support, jitter, test-mode support, typing, runtime
   dependencies — each fact with a citation URL.
2. An evaluation of each library against R1–R6.
3. A recommendation (one library) with the reasoning, and the runner-up.
4. An adoption plan: how call sites migrate (show one before/after code
   example for an `httpx` call), test setup, rollout steps, and risks.
5. A "Sources" list with access dates.

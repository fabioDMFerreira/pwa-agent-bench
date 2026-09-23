# P1 — Plan webhook delivery for the event store

Work only inside `bench/P1/`. Do not modify any code — this is a planning
task; the only deliverable is a document.

`bench/P1/src/eventstore/` is a minimal append-only event store (read
`store.py`, `events.py` and `tests/test_store.py`).

We want to add **outbound webhook delivery**: external systems register an
HTTP endpoint (optionally filtered by event type) and receive each newly
appended event as an HTTP POST. Deliveries must be reliable:

- retries with **exponential backoff** for transient failures,
- **idempotency keys** so receivers can de-duplicate,
- a **dead-letter queue** for deliveries that exhaust retries or fail
  permanently, with a way to re-drive them,
- receivers must be able to verify a request came from us.

## Deliverable

Write `bench/P1/PLAN.md` — an implementation plan another engineer could
execute without further questions. No code changes. It should cover at
least: architecture and where the feature hooks into the existing store, data
model and state machine for a delivery, the retry/backoff policy (with
concrete numbers), which failures are retryable vs permanent, idempotency-key
design, DLQ and re-drive, request signing, ordering and delivery guarantees,
durability/crash behaviour, observability, a test plan, and a step-by-step
rollout / task breakdown with risks.

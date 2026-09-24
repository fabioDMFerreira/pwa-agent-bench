# Plan: Outbound Webhook Delivery for the Event Store

**Status:** implementation plan (planning task P1 — no code changes in this deliverable)
**Scope:** `bench/P1/` only. Add outbound webhook delivery to the existing
`eventstore` package. This document is the sole deliverable.

**Environment constraints (from `pyproject.toml` / `conftest.py`):**
- Python ≥ 3.11, **stdlib + pytest only** — no new third-party dependencies.
  All networking, persistence, and crypto use the standard library
  (`urllib.request`, `sqlite3`, `hmac`, `hashlib`, `secrets`, `json`,
  `threading`, `time`).
- Tests run from `bench/P1/` via `python3 -m pytest -q` (conftest adds
  `bench/P1/src` to `sys.path`).

---

## 1. Goals and non-goals

### Goals
1. External systems can **register an HTTP endpoint** (optionally filtered by
   event type).
2. Every newly appended event is delivered to each **matching** endpoint as an
   HTTP **POST**.
3. Delivery is **reliable**:
   - retries with **exponential backoff** on transient failures;
   - **idempotency keys** so receivers can de-duplicate;
   - a **dead-letter queue (DLQ)** for permanently failed deliveries, with a
     **re-drive** mechanism;
   - **request signing** so receivers can verify authenticity.
4. Delivery state is **durable**: a crash or restart never loses an event
   (at-least-once), and re-drive covers gaps (no silent drops).
5. **Non-blocking**: webhook delivery must never block, delay, or undo an
   `EventStore.append()` call. The existing append path stays fast and
   unchanged in behaviour.

### Non-goals
- Multi-process HA / distributed coordination (this store is in-process +
  local file; we assume a single process per deployment).
- TLS/mTLS termination — out of scope; receivers may require HTTPS, we just
  POST to the given URL.
- Managing receiver-side processing; we deliver, they de-duplicate.

---

## 2. Where the feature hooks into the existing store

The store (`src/eventstore/store.py`) has three properties we exploit:

1. **`EventStore.subscribe(listener)`** — in-process listeners are called
   synchronously, in registration order, *after* each successful append, and
   a raising listener does **not** undo the append and does not stop other
   listeners (see `store.py:63-68`). This is the natural integration point.
2. **Global `position`** — a 1-based, gap-free, monotonically increasing
   position on every `Event`. It is a reliable cursor for "which events exist"
   and powers both per-endpoint cursors and crash reconciliation.
3. **JSONL persistence + `_load()`** — when `path` is set, events are replayed
   on construction. Webhook delivery state must have **equivalent**
   durability or a restart would re-deliver (or drop) events.

### Design choice: the **Outbox** pattern

We do **not** send HTTP from inside `append()`. Instead:

```
append() ──(existing listener callback)──> WebhookGateway.enqueue(event)
                                                │
                                                ▼
                                 durable outbox + delivery state (sqlite3)
                                                │
                                                ▼
                              DeliveryWorker (background thread)
                                                │
                                                ▼
                              HTTP POST (+retries) ──> DLQ on permanent failure
```

**Why an outbox + worker thread instead of synchronous delivery in `append`:**
- Keeps the append path fast and non-blocking (a slow receiver must not stall
  writers).
- The durable outbox makes delivery **crash-safe** and gives us a clean
  **at-least-once** guarantee and a natural **DLQ**.
- Reusing `subscribe()` means we make **minimal changes to `store.py`** — in
  fact, *none*. `EventStore` is untouched; the gateway is an external
  collaborator attached via the public API.

### New modules (all under `bench/P1/src/eventstore/webhooks/`)

| File | Responsibility |
|------|----------------|
| `__init__.py` | Public exports: `WebhookGateway`, `DeliveryError`, etc. |
| `model.py` | Dataclasses: `WebhookEndpoint`, `OutboxRecord`, `DeliveryAttempt`, `DeliveryState` (enum). |
| `gateway.py` | `WebhookGateway`: endpoint registry, enqueue hook (the `subscribe` listener), DLQ API, re-drive API. |
| `worker.py` | `DeliveryWorker`: background thread, claim loop, backoff scheduling, HTTP POST. |
| `signing.py` | HMAC-SHA256 signing + verification helpers. |
| `whstore.py` | `WebhookStore`: sqlite3 persistence for endpoints, outbox, delivery state, DLQ. |
| `http.py` | `send_post(url, body, headers, timeout) -> (status, body)` using `urllib.request`. |

> Naming note: the sqlite-backed state module is deliberately named
> **`whstore.py`**, not `store.py`, so it never reads as a shadow of the
> top-level `eventstore.store.EventStore` (grep, IDE navigation, and
> imports all stay unambiguous).

### Integration point (the *only* wiring required)

In the application that constructs the store, after creating `EventStore`,
attach the gateway:

```python
store = EventStore(path="events.jsonl")
gw = WebhookGateway(store)          # calls store.subscribe(gw._on_append)
worker = DeliveryWorker(gw)
worker.start()
```

Because we use the existing `subscribe()` API, **`store.py`, `events.py`, and
`errors.py` are not modified.** This keeps the change surface small and the
existing 6 tests green.

---

## 3. Data model

All durable state lives in one SQLite DB (default `webhooks.sqlite3`),
opened with `sqlite3.connect(path, check_same_thread=False)` and guarded by a
`threading.Lock` around writes. SQLite gives us ACID writes (a record is
committed or not) which is what we need for crash durability, with zero
third-party dependencies.

### 3.1 `endpoints` table — the registered receivers

| Column | Type | Notes |
|--------|------|-------|
| `endpoint_id` | TEXT PK | e.g. `"ep_demo"` (operator-chosen) or generated `ep_<8hex>` |
| `url` | TEXT | target HTTPS URL |
| `event_types` | TEXT | NULL = all types; else JSON list, e.g. `["OrderPlaced","Shipped"]` |
| `secret` | TEXT | HMAC secret for this endpoint (generated `whsec_<32hex>` if not supplied) |
| `enabled` | INT (0/1) | disabled endpoints stop receiving *new* events (see §6.3) |
| `per_endpoint_serial` | INT (0/1) | `1` (default) = serial in-order delivery for this endpoint; `0` = allow fan-out (see §9.1) |
| `created_at` | REAL | unix ts |
| `last_seen_ok` | REAL | ts of last successful delivery (NULL if never) |

**Matching rule:** an endpoint matches an event iff `event_types IS NULL`
*or* `event.type IN (the decoded list)`. Matching is evaluated **at enqueue
time** (not at delivery time), so a newly registered endpoint only receives
events appended *after* registration — see §9 ordering guarantees.

### 3.2 `outbox` table — the durable queue (the source of truth)

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK AUTOINCREMENT | stable per delivery task |
| `endpoint_id` | TEXT FK | which endpoint |
| `event_id` | TEXT | the `Event.id` |
| `position` | INT | the `Event.position` (cursor) |
| `payload` | TEXT | **canonical JSON** body (exactly what is POSTed & signed — see §7) |
| `state` | TEXT | `PENDING` \| `IN_FLIGHT` \| `RETRY` \| `DELIVERED` \| `DEAD` (see §4) |
| `attempts` | INT | number of POSTs made (starts 0) |
| `max_attempts` | INT | 6 (see §5) |
| `next_attempt_at` | REAL | unix ts when the record is eligible to be (re)sent |
| `last_status` | TEXT | last HTTP status or error code, e.g. `"503"`, `"timeout"`, `"404"` |
| `created_at` | REAL | enqueue ts |
| `updated_at` | REAL | last state change ts |
| `delivered_at` | REAL | ts of successful delivery (NULL until DELIVERED) |

**Indexes** for the worker's hot query and crash detection:
- `idx_outbox_state_next (state, next_attempt_at)`
- `idx_outbox_endpoint_pos (endpoint_id, position)` — used for cursor/
  reconciliation and for the duplicate-insert guard.

**Uniqueness / de-duplication at the outbox level:** a unique index on
`(endpoint_id, event_id)` makes a double `enqueue` a no-op (the same event is
never queued twice for the same endpoint), which is important because the
`subscribe` callback and the crash-reconciliation path (see §4) can both try
to enqueue. This is the *producer-side* de-dup; the *receiver-side* de-dup is
the idempotency key (§7).

### 3.3 `delivery_attempts` table — audit trail (optional but recommended)

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `outbox_id` | INT FK | which delivery task |
| `attempt_no` | INT | 1-based |
| `started_at` | REAL | |
| `outcome` | TEXT | `OK` \| `RETRYABLE` \| `PERMANENT` \| `ERROR` |
| `status` | TEXT | HTTP status or error code |
| `latency_ms` | INT | |
| `error` | TEXT | message |

This powers the observability in §12 and is cheap to keep.

### 3.4 DLQ

The DLQ is **the same `outbox` table filtered by `state = 'DEAD'`** — not a
separate table. A record is dead-lettered by flipping `state` to `DEAD`
(retaining the full payload, attempts, and last error). This keeps one source
of truth and makes re-drive trivial (§11). A `dead_reason` column
(`RETRY_EXHAUSTED` | `PERMANENT` | `DISABLED`) records *why* it was parked.

> Why not a separate `dead_letter` table? A separate table would require
> moving rows (a copy, risking a gap) and duplicate the schema. In-place
> state flips are atomic in SQLite and cannot lose the record.

---

## 4. Delivery state machine

```
            ┌─────────────┐
   enqueue  │             │  POST returns 2xx
            ▼             │ ─────────────────────────────┐
        ┌─────────┐       │                              ▼
        │ PENDING │       │                          ┌───────────┐
        └────┬────┘       │                          │ DELIVERED │  (terminal)
             │ worker      │                          └───────────┘
     claims  │             │
             ▼             │
        ┌───────────┐      │  POST returns retryable (5xx / 429 /
        │ IN_FLIGHT │      │  timeout / conn error) and attempts < max
        └─────┬─────┘      │ ─────────────────────────┐
              │             │                         ▼
              │             │                    ┌─────────┐
              │             │                    │ RETRY   │──(scheduled)──► back to PENDING
              │             │                    └────┬────┘
              │             │                         │ attempts reach max
              │             │                         ▼
              │             │                    ┌─────────┐
              │             │  POST returns 4xx   │  DEAD   │  (terminal, in DLQ)
              └─────────────┴─(permanent)────────►└─────────┘
```

**States:**
- **`PENDING`** — eligible to be picked up by the worker (created on enqueue).
- **`IN_FLIGHT`** — the worker has claimed the record and is mid-POST. This
  state is what makes crash detection possible (§10): any record still
  `IN_FLIGHT` after a restart is a crashed send and must be reclaimed.
- **`RETRY`** — a transient failure was recorded; the record is *scheduled*
  for a later attempt via `next_attempt_at = now + backoff(attempts)`. It is
  *not* eligible until that time passes; the worker flips it to `PENDING`
  (atomic `UPDATE ... WHERE state='RETRY' AND next_attempt_at <= now`) once
  the timer elapses.
- **`DELIVERED`** — a 2xx was received. Terminal. `delivered_at` set.
- **`DEAD`** — retries exhausted **or** a permanent (non-retryable) failure.
  Terminal until **re-driven** (§11). Lives in the DLQ.

**Eligibility (hot path, every tick):** a record is eligible iff
`state='PENDING' AND next_attempt_at <= now`. In the default serial mode the
claim is per-endpoint (next-oldest, `ORDER BY position LIMIT 1`, only for
endpoints with no current `IN_FLIGHT` row) — see §5 (concurrency) and §9.1.
Keeping `RETRY` and `PENDING` distinct (instead of conflating them) makes the
state machine explicit and the "when may this be sent" invariant trivially
visible: a record is eligible iff `state='PENDING'`.

**Invariant:** a record is always in exactly one state; every transition is a
single atomic `UPDATE ... WHERE state = <expected>` so a torn write is
impossible (SQLite commit is atomic).

---

## 5. Retry & backoff policy (concrete numbers)

**Policy:** exponential backoff with full jitter.

- **`max_attempts` = 6** total attempts (the initial send counts as attempt 1).
- **Base delay** = `5 s`.
- **Multiplier** = `2×`.
- **Cap** = `1800 s` (30 min) — a single record's delay never exceeds this.
- **Jitter** = **full jitter**: actual wait = `random.uniform(0, min(cap,
  base * 2 ** (attempt-2)))`. Full jitter avoids thundering-herd when many
  records back off together and is the recommended pattern for HTTP retries.

Delay before attempt *n* (n ≥ 2), before jitter, capped:

| Attempt | Wait (no jitter) | Cumulative (no jitter) |
|:-------:|:----------------:|:----------------------:|
| 1 | 0 s (initial) | 0 s |
| 2 | 5 s | ~5 s |
| 3 | 10 s | ~15 s |
| 4 | 20 s | ~35 s |
| 5 | 40 s | ~75 s |
| 6 | 80 s | ~155 s (final) |

So a permanently-transient receiver is retried over **~2.5 minutes** before it
is dead-lettered after 6 attempts. (If a longer soak is desired, the numbers
above are module constants — `MAX_ATTEMPTS`, `BACKOFF_BASE`, `BACKOFF_FACTOR`,
`BACKOFF_CAP` — so they can be tuned without logic changes.)

**Worker tick:** the worker polls the DB every **`1 s`**: first it ages out
due `RETRY` rows into `PENDING` (atomic `UPDATE outbox SET state='PENDING'
WHERE state='RETRY' AND next_attempt_at <= now`). Then, for each endpoint that
currently has **no** `IN_FLIGHT` record (see the concurrency note below), it
claims that endpoint's next-oldest eligible record:
`SELECT id FROM outbox WHERE state='PENDING' AND endpoint_id=? AND
next_attempt_at <= now ORDER BY position LIMIT 1`. This 1 s tick is the
granularity of "when" — sub-second precision is not needed for webhooks.

**Per-request timeout:** each POST has a **`10 s`** socket timeout
(`timeout=10` on `urllib.request.urlopen`). A request not answered within 10 s
is a transient failure (retryable).

**Concurrency:** the worker uses a small thread pool (default **`4`
workers**, bounded by `max_workers`) so that *different* endpoints are served
in parallel and one slow receiver does not stall the others. **Within a single
endpoint, sends are serial by default** (see §9.1): the worker claims at most
one `IN_FLIGHT` record per endpoint, so per-endpoint in-order delivery is
preserved while endpoints still run concurrently with each other. Records are
claimed with a per-endpoint
`SELECT id FROM outbox WHERE state='PENDING' AND endpoint_id=? AND
next_attempt_at <= now ORDER BY position LIMIT 1` issued only for endpoints
with no current `IN_FLIGHT` row, so a record is never sent concurrently by two
workers (and never out of order for its own endpoint).

---

## 6. Failure classification

### 6.1 Retryable (transient)
- **HTTP `5xx`** (`500`, `502`, `503`, `504`).
- **HTTP `429`** (rate limited). If a `Retry-After` header is present and is a
  reasonable delay (≤ `BACKOFF_CAP`), use it (with jitter) instead of the
  computed backoff; otherwise use computed backoff.
- **Network / socket errors**: connection refused, reset, DNS failure,
  `timeout`, `URLError` with no HTTP status.
- Any `urllib` exception that does **not** carry an HTTP status.

### 6.2 Permanent (non-retryable)
- **HTTP `400`** (bad request — payload will never fix itself),
  **`401`** / **`403`** (auth — we are signed correctly, this is a
  configuration/credential problem on the receiver), **`404`** (endpoint
  gone), **`405`** (method not allowed), **`410`** (gone).
  → these go **straight to `DEAD`** (`dead_reason = PERMANENT`) with no
  retries, because retrying a bad URL/credential is wasted load and hides the
  real problem.
- **Undeliverable at transport level with a definitive answer**: e.g. URL
  scheme is not `http/https`, or the host resolves to nothing and the error is
  a `gaierror` *persisted* across attempts (treat as transient on first pass —
  DNS can be flaky — so DNS errors are retryable until attempts exhaust).

**Decision rule (implemented in `http.py`):**
```
if response.status is None          -> RETRYABLE   (transport error)
elif 200 <= status < 300           -> DELIVERED
elif status == 429                 -> RETRYABLE   (honour Retry-After)
elif status in {400,401,403,404,405,410} -> PERMANENT
elif 300 <= status < 400           -> RETRYABLE   (unexpected redirect; we do not follow)
elif 500 <= status < 600           -> RETRYABLE
else                               -> RETRYABLE   (default: be safe, retry)
```
Redirects (`3xx`) are **not** followed automatically; they are treated as
retryable so a misconfigured URL that redirects loudly surfaces rather than
silently POSTing to an unexpected host.

### 6.3 Endpoint `enabled = 0`
When an endpoint is disabled, *newly appended* events are **not** enqueued
(matching skips disabled endpoints). Records already in the outbox for that
endpoint are left alone (they will still be delivered) — disabling is about
stopping the *firehose*, not cancelling in-flight work. A `PATCH`/update API
`{"enabled": false}` sets the flag.

---

## 7. Idempotency-key design

**Key format:** `wh-v1-<endpoint_id>-<event_id>`
- **Version prefix** `wh-v1` — lets us change the scheme later without
  colliding with old keys.
- **`endpoint_id`** — scoping per receiver; the *same event* delivered to two
  endpoints gets two different keys (each receiver's de-dup namespace is
  independent).
- **`event_id`** — the store's `Event.id`, unique and stable.

**Stability property (the crucial one):** the key is a pure function of
`(endpoint_id, event.id)`, **not** of attempt number, position, or timestamp.
Therefore **every retry of the same delivery carries the identical
idempotency key**. A receiver that de-dupes on this key will process the event
exactly-once *from its perspective*, even though our system guarantees
at-least-once. This is the standard "at-least-once + idempotent receiver =
effectively-once" composition.

**Transport:**
- Sent as the HTTP header **`Idempotency-Key: wh-v1-<endpoint_id>-<event_id>`**.
- Also embedded in the JSON body as `"idempotency_key"` (so a receiver that
  only persists the body can still de-dup, and debugging is self-contained).
- The payload **never** contains the attempt number in a way that changes the
  idempotency key. (The body *does* carry an `"attempt"` field for
  observability — see §7.1 — but receivers **must** key off
  `idempotency_key`, not `attempt`.)

**What receivers should do (documented in the receiver guide, §7):**
- Persist the `idempotency_key` on first successful processing.
- On receiving a key they have already processed, respond `200` **without**
  re-processing.
- Retain keys for at least the maximum delivery window (our retries span
  ~2.5 min; recommend receivers keep keys ≥ 7 days to be safe across DLQ
  re-drives).

### 7.1 Canonical request body

To make signing (§8) and idempotency deterministic, the **exact** bytes POSTed
and signed are defined precisely:

```
body  = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
```

where `payload` is:
```json
{
  "idempotency_key": "wh-v1-<endpoint_id>-<event_id>",
  "event": { ...Event.to_dict()... },
  "delivered_at": <unix float of this send>,
  "attempt": <int, 1-based>
}
```

`sort_keys` + fixed separators mean two runs produce byte-identical bodies for
the same logical payload (except the two volatile fields `delivered_at` and
`attempt`, which are *expected* to differ between retries and are covered by
the signature).

**Persistence rule:** `outbox.payload` stores only the **static** part
`{"idempotency_key": ..., "event": ...}` (no `delivered_at`, no `attempt`). At
send time the worker injects `delivered_at` (its clock) and `attempt`
(derived as `outbox.attempts + 1`, so it is always consistent with
`outbox.attempts` — it is never stored), serializes canonically per the rule
above, signs that exact byte string, and POSTs it.

---

## 8. Request signing

**Scheme:** HMAC-SHA256 (stdlib `hmac` + `hashlib`).

**Secret:** each endpoint has its own `secret` (see §3.1), generated as
`whsec_` + 32 hex chars (`secrets.token_hex(16)`). A per-endpoint secret means
one receiver's secret leak does not compromise the others.

**What is signed (v1):**
```
signed_string = f"{timestamp}.".encode("utf-8") + body_bytes   (bytes)
signature     = hmac.new(secret, signed_string, hashlib.sha256).hexdigest()
```
where `timestamp` is the **integer** unix seconds of this send — the exact
integer placed in the `Webhook-Timestamp` header — and `body_bytes` is the
exact canonical JSON body that is POSTed (§7.1). `delivered_at` in the body is
`float(timestamp)`, so the two are consistent by construction.

**Headers sent on every POST:**
| Header | Value |
|--------|-------|
| `Content-Type` | `application/json` |
| `User-Agent` | `eventstore-webhook/1.0` |
| `Webhook-Timestamp` | `<int unix seconds>` |
| `Webhook-Signature` | `v1=<64-hex-hmac>` |
| `Idempotency-Key` | `wh-v1-<endpoint_id>-<event_id>` |

**Verification (receiver side):** recompute the HMAC over
`f"{Webhook-Timestamp}.{raw_body}"` with the shared secret and compare against
the `v1=` value using **`hmac.compare_digest`** (constant-time). Reject if the
timestamp is more than **±5 minutes** from now (replay protection).

**Known test vector (must be asserted in tests — see §13.3):**
- `secret = b"whsec_demo0123456789abcdef"`
- `timestamp = "1700000000"`
- `body =
  {"attempt":1,"delivered_at":1700000000.0,"event":{"data":{"total":5},"id":"e1","position":1,"recorded_at":100.0,"stream":"order-42","type":"OrderPlaced","version":1},"idempotency_key":"wh-v1-ep_demo-e1"}`
  (this is exactly `json.dumps(payload, sort_keys=True, separators=(",",":"))`
  for the shown payload, with `delivered_at == float(timestamp)` per the rule
  above)
- `signed_string = b"1700000000." + body`
- **Expected signature:** `0451197e797a9947ba8c18926f866a4563520ab5c6c29157dbc2dc4794b5d12a`

`signing.py` must expose both `sign(secret, timestamp, body_bytes) -> str`
and `verify(secret, timestamp, body_bytes, signature, now=None, max_skew=300)
-> bool` so receivers (or our tests) can verify.

**Rotation:** a `POST .../rotate-secret` API generates a new secret and stores
it; old deliveries keep signing with the secret they were created with until
re-drive (note this in the receiver guide: after rotation, in-flight/old
deliveries will fail verification until re-driven, so rotate during low
traffic). v1 keeps one active secret per endpoint (rotation = replace); a
two-secret grace period is a documented future extension, not part of this
plan.

---

## 9. Ordering & delivery guarantees

### 9.1 The guarantee
- **At-least-once**: every event matching an enabled endpoint is POSTed at
  least once. (Retries and crash-recovery can cause duplicates; receivers
  de-dup via the idempotency key — §7.)
- **Per-endpoint in-order (default mode)**: within a *single endpoint*,
  deliveries are **serial** — the worker holds at most one `IN_FLIGHT` record
  per endpoint (a per-endpoint latch), and the next-oldest pending record for
  that endpoint is only claimed once the current one reaches `DELIVERED`. So
  event N for endpoint E is never POSTed after N+1 has been POSTed, in
  steady-state (no crash between send and record-success).
  - `per_endpoint_serial = True` is the **default** and what this guarantee
    assumes. The tunable exists because a per-endpoint latch bounds per-endpoint
    throughput by the receiver's latency; for endpoints that *do not care*
    about order (e.g. metric sinks), an operator may set
    `per_endpoint_serial = False` for that endpoint to let the worker pool
    fan out. Ordering is then best-effort for that endpoint and is explicitly
    out of guarantee (see §9.2).
- The claim query therefore is per endpoint:
  `SELECT id FROM outbox WHERE state='PENDING' AND endpoint_id=? AND
  next_attempt_at <= now ORDER BY position LIMIT 1`, and the worker only runs
  this for endpoints that currently have **no** `IN_FLIGHT` record.

### 9.2 What we do NOT guarantee (stated explicitly)
- **Cross-stream global ordering**: the store itself only guarantees ordering
  within a stream and a global `position`. We do not impose a global total
  order across independent streams on the wire (it isn't one the store gives
  us per-stream).
- **Cross-endpoint ordering**: endpoints are independent; we make no promise
  about the relative order in which two different endpoints receive the same
  event.
- **Strict "no duplicate"**: we are at-least-once; a receiver that is not
  idempotent will see duplicates after a crash-retry or 5xx retry. This is the
  accepted trade for reliability and is exactly what the idempotency key is
  for.
- **Unbounded latency under a dead endpoint**: if a receiver is down, its
  backlog grows and (in default serial mode) no further events for that
  endpoint are attempted until one succeeds or retries exhaust — we deliver in
  order and do not drop or reorder to keep up. Operators who prioritise
  throughput over order for a specific endpoint can opt into fan-out
  (`per_endpoint_serial = False`, §9.1).

### 9.3 Why "enqueue-time matching" matters for ordering
Because matching happens at enqueue time (§3.1), the set of events an endpoint
receives is fixed at registration; we never have to decide mid-stream whether
a newly-registered endpoint should receive *historical* events. This keeps the
per-endpoint cursor simple: the cursor starts at `head_position` at
registration time and only moves forward.

---

## 10. Durability & crash behaviour

**Goal:** no event is lost and no event is silently dropped on crash/restart.

> **Assumption:** this guarantee is only as durable as the event store itself.
> It holds when the store is run with `path` set (JSONL persistence); in
> memory-only mode (`path=None`) a crash loses the events regardless of the
> webhook feature, because the events were never durable to begin with. The
> plan therefore assumes `path` is configured for any deployment that needs
> crash-safe delivery.

### 10.1 Durability layers
1. **Events** are already durable in the store's JSONL (existing behaviour).
2. **Delivery state** is durable in SQLite: every transition
   (`PENDING`→`IN_FLIGHT`, `→RETRY`/`DELIVERED`/`DEAD`) is a committed
   `UPDATE`. The outbox row is inserted (as `PENDING`) **before** any send.
3. Because the enqueue is the `subscribe` callback (synchronous, in-process),
   the outbox row is written *before* `append()` returns to the caller. So at
   the moment an append succeeds, the fact that "this event must be delivered
   to endpoint X" is already durable.

### 10.2 Crash scenarios and recovery (on construction / `start()`)
The worker, on `start()`, runs a **reconciliation pass** before normal work:

1. **Stale `IN_FLIGHT`** → any record still `IN_FLIGHT` (we crashed mid-POST)
   is reset to `PENDING` with `next_attempt_at = now` (at-least-once: we
   re-send, receiver de-dups). This is the key "no lost deliveries" step.
2. **Gap detection (the safety net):** for each endpoint, compare
   `max(position) where state = 'DELIVERED'` (its cursor) against the store's
   `head_position`. For any `event.type`-matching event with
   `position > cursor` that is **not** present in the outbox as a
   non-`DEAD` row (check `outbox` via the unique `(endpoint_id, event_id)`
   index), **re-enqueue** it. This catches the narrow window where the
   `subscribe` callback was about to run but the process died *between* the
   JSONL write and the outbox insert — i.e., "event persisted but enqueue not
   yet durable." Because reconciliation runs on every start and is
   idempotent (the unique index prevents double-enqueue), this closes the gap
   without any extra machinery.
   - **Cost control:** this is an O(events-since-cursor) scan per endpoint,
     done once at startup, not per append. Fine for the in-process store's
     scale; if `head_position` is very large, the scan uses the store's
     `read_all(after_position=cursor)` which is already index-free but
     sequential and cheap in Python for moderate sizes.
3. **`RETRY`** rows with `next_attempt_at > now` are left alone (their timer
   simply continues across the crash).
4. **`DEAD`** rows are left alone (they stay in the DLQ until re-driven —
   §11).

**Net effect:** after any crash/restart, the system reconverges to a state
where every matching, non-delivered, non-dead event is represented exactly
once in the outbox, and all in-flight sends are re-driven.

### 10.3 Crash *during* reconciliation
Reconciliation itself writes are atomic (each re-enqueue is one committed
insert guarded by the unique index). A crash mid-reconciliation just leaves a
partial set of re-enqueues; the next start repeats the pass and fills the
rest. Safe to run repeatedly.

### 10.4 Ordering under crash
A re-driven `IN_FLIGHT`→`PENDING` record may be re-sent *after* a later event
in the same stream has already been delivered. This is the unavoidable
consequence of at-least-once + a crash between "send" and "record success".
The receiver's idempotency key makes the *effect* safe; strict ordering of the
*wire messages* across a crash boundary is not promised (and is generally
impossible for a reliable system). This is documented as an explicit,
accepted limitation.

---

## 11. DLQ & re-drive

### 11.1 Entering the DLQ
A record enters the DLQ (`state='DEAD'`) via three paths (§5, §6):
- **`RETRY_EXHAUSTED`** — 6 attempts, all transient → park it.
- **`PERMANENT`** — a `4xx` permanent status → park it immediately.
- **`DISABLED`** — (optional operator action) force-park a stuck record.

`dead_reason` records which path. The full `payload`, `attempts`, and
`last_status` are retained so re-drive and debugging have everything.

### 11.2 Inspecting the DLQ
`WebhookGateway.dead_letters(limit=50, endpoint_id=None) -> list[OutboxRecord]`
returns the current DLQ, newest `updated_at` first. (The `delivery_attempts`
table gives the full per-attempt history for any `outbox_id`.)

### 11.3 Re-drive
`WebhookGateway.redrive(outbox_id=None, endpoint_id=None, reason=None,
reset_attempts=True) -> int` (count re-driven):
- Selects `DEAD` rows (all, or by `endpoint_id`).
- Sets `state = 'PENDING'`, `next_attempt_at = now`, and — if
  `reset_attempts=True` — `attempts = 0` and `dead_reason = None`.
- Returns how many were re-queued.

Because re-drive reuses the **same** `outbox` row (same `id`, same
`endpoint_id`+`event_id`), the **idempotency key is unchanged** — a receiver
that already processed the event will de-dup it, and a receiver that *didn't*
(now that it's fixed) will process it. This is exactly the semantics we want
for a DLQ: re-drive is safe and idempotent on the receiver side.

A convenience `redrive_all()` (i.e., `redrive()`) is provided for the common
"the receiver is back up, replay everything dead" case.

### 11.4 Purge
`WebhookGateway.purge_dead(older_than_days=7) -> int` removes `DEAD` rows
older than a threshold *that have been successfully re-driven at least once*
(or, operator policy, older than N days unconditionally). Purging is
deliberately conservative: default policy only purges `DEAD` rows where
`dead_reason` was resolved by a successful re-drive; purely-exhausted,
never-delivered records are kept (they may represent a real outage worth
investigating). The exact purge policy is an operator knob, defaulting to
"keep everything" (no auto-purge) — **default is safe: nothing is deleted
automatically.**

---

## 12. Observability

### 12.1 Structured logging
`logging.getLogger("eventstore.webhooks")`, one record per transition:
- `enqueue endpoint=%s event=%s pos=%s`
- `delivery_start endpoint=%s event=%s attempt=%s`
- `delivery_ok endpoint=%s event=%s attempt=%s status=200 latency_ms=%s`
- `delivery_retry endpoint=%s event=%s attempt=%s status=%s next_in=%s`
- `delivery_dead endpoint=%s event=%s reason=%s last_status=%s`
- `redrive endpoint=%s count=%s`
- `reclaim_stale_inflight count=%s`
- `reconcile_gaps endpoint=%s enqueued=%s`

### 12.2 Metrics (exposed as attributes / a `stats()` method, plus log lines)
- `enqueued_total`, `delivered_total`, `retry_total`, `dead_total`
- `in_flight` (current `IN_FLIGHT` count), `pending` (current `PENDING`+`RETRY`)
- `oldest_pending_age_seconds` (max `now - next_attempt_at` over pending —
  **lag** indicator), `oldest_dead_age_seconds`
- `per_endpoint`: `last_seen_ok`, `dead_count`, `pending_count`
- `reclaim_stale_total`, `reconcile_enqueued_total`

A `WebhookGateway.stats() -> dict` returns these; an operator can poll it or
ship the log lines. (No Prometheus client — stdlib only.)

### 12.3 Alerts (operator guidance)
- `oldest_pending_age_seconds > 5 min` → receiver is degraded.
- `dead_total` increasing → an endpoint is permanently failing; check DLQ.
- `reclaim_stale_total` > 0 on a normal start → a crash happened; investigate.

---

## 13. Test plan

Tests go in `bench/P1/tests/test_webhooks.py` (plus `test_signing.py`).
Stdlib + pytest only. All timing is **injected** (a `clock` and a fake
`http_sender`) so tests are deterministic and fast — **no real sleeps, no
real network.**

**Shared fakes:**
- `FakeClock`: `now()` returns a mutable value; `advance(s)`.
- `FakeSender`: records `(url, headers, body)`; returns a configurable
  sequence of `(status, body)` or raises. Lets tests script 5xx→200,
  404, timeout, etc.
- `FakeStore`: a real `EventStore` (in-memory) so we test against the actual
  integration point.

### 13.1 Happy path
1. **Enqueue on append**: register endpoint (all types), append 1 event →
   exactly one `PENDING` outbox row with the right `endpoint_id`,
   `event_id`, `position`, and payload.
2. **Delivery**: run worker tick → row becomes `DELIVERED`,
   `delivered_at` set, `FakeSender` saw one POST with correct URL,
   `Content-Type`, `Idempotency-Key`, and signature.
3. **Filtering**: endpoint filtered to `["OrderPlaced"]`; append
   `OrderPlaced` + `Shipped` → only `OrderPlaced` enqueued.
4. **Multi-endpoint**: two endpoints (one all-types, one filtered); one append
   → correct number of rows, correct matching.

### 13.2 Retry & backoff
5. **Transient retry**: sender returns `503` twice then `200` →
   `attempts == 3`, state `DELIVERED`, same idempotency key on all three
   POSTs, backoff delays follow the schedule (assert `next_attempt_at`
   increased by the computed waits using the fake clock).
6. **Exhaustion → DLQ**: sender always `503` → after 6 attempts state
   `DEAD`, `dead_reason = RETRY_EXHAUSTED`, in `dead_letters()`.
7. **Permanent → DLQ immediately**: sender `404` → one attempt, `DEAD`,
   `dead_reason = PERMANENT`, **no** retries.
8. **Jitter bounds**: with a seeded `random`, assert each wait is
   `0 <= wait <= min(cap, base*2**(a-2))`.
9. **Retry-After**: sender `429` + `Retry-After: 7` → next wait ≈ 7 s (±jitter
   ceiling respected, i.e. ≤ cap).

### 13.3 Idempotency & signing
10. **Key stability**: re-drive / re-send the same delivery N times → all N
    POSTs carry the identical `Idempotency-Key` header.
11. **Known signing vector** (§8): `sign(b"whsec_demo0123456789abcdef","1700000000",body)`
    equals `0451197e797a9947ba8c18926f866a4563520ab5c6c29157dbc2dc4794b5d12a`;
    `verify(...)` returns `True`; a flipped byte in the body or a stale
    timestamp (>5 min) returns `False`.
12. **Signature present & correct on the wire**: decode the sent
    `Webhook-Signature` header and recompute over the sent bytes → match.

### 13.4 DLQ & re-drive
13. **Re-drive exhausted**: `redrive(outbox_id)` → state `PENDING`,
    `attempts==0`, sender now `200` → `DELIVERED`; idempotency key unchanged.
14. **Re-drive permanent**: same for a `PERMANENT` record.
15. **Re-drive is idempotent for the receiver**: simulate a receiver that has
    already seen the key → it ignores the re-drive (assert our POSTs always
    carry the same key so the *receiver's* de-dup holds; we assert key
    equality, not receiver internals).
16. **Purge conservative**: default `purge_dead` deletes nothing unless the
    record was resolved; assert no auto-deletion.

### 13.5 Crash & durability
17. **Stale IN_FLIGHT reclaim**: force a row to `IN_FLIGHT`, restart worker
    (new `DeliveryWorker` on the same DB) → row reclaimed to `PENDING` and
    delivered.
18. **Gap reconciliation**: build a store where an event exists in JSONL but
    its outbox row is missing (simulate "died between persist and enqueue") →
    on start, reconciliation re-enqueues exactly that event once (unique index
    prevents duplicates on a second run).
19. **Persistence round-trip**: run deliveries into a sqlite file, close,
    reopen with a fresh `WebhookStore` → all rows/states intact;
    `DELIVERED` stays delivered (no re-send of already-delivered).
20. **Restart does not double-deliver delivered events**: after a full
    `DELIVERED` set, restart → zero new POSTs for already-delivered rows.

### 13.6 Ordering
21. **Per-stream in-order**: 5 events in one stream, sender records order →
    delivered in `position` order for that endpoint.
22. **Slow endpoint isolation**: endpoint A slow (returns after "delay"),
    endpoint B fast → B's events delivered while A is busy (pool isolation);
    A still ends in-order.

### 13.7 Regression
23. **Existing 6 tests still pass** (we don't touch `store.py`/`events.py`).
24. **Append not blocked**: with a slow-failing sender, `append()` returns
    promptly (assert elapsed < threshold) — delivery is async.

**Determinism:** every timing assertion uses the injected `FakeClock` and a
seeded `random.Random`; no test sleeps more than 0 ms of wall time.

---

## 14. Step-by-step rollout / task breakdown

Ordered so each step is independently testable and leaves the repo green.

| # | Task | Files | Acceptance |
|:-:|------|-------|-----------|
| 1 | `model.py`: `WebhookEndpoint`, `OutboxRecord`, `DeliveryState` enum, constants (`MAX_ATTEMPTS=6`, `BACKOFF_BASE=5`, `BACKOFF_FACTOR=2`, `BACKOFF_CAP=1800`, `MAX_WORKERS=4`, `REQUEST_TIMEOUT=10`). | `model.py` | Unit tests for dataclasses & enum. |
| 2 | `whstore.py`: `WebhookStore` (sqlite3 schema DDL, CRUD, claim, unique index). | `whstore.py` | Tests: schema, insert, claim, unique dup, state flips atomic. |
| 3 | `signing.py`: `sign`, `verify`, `make_secret`. | `signing.py` | Known-vector test (§8) passes; `verify` rejects stale/corrupt. |
| 4 | `http.py`: `send_post` with timeout + status capture (no redirect follow). | `http.py` | Unit test against `FakeSender`/local `http.server`. |
| 5 | `gateway.py` (part 1): endpoint register/update/disable + `subscribe` wiring + `_on_append` enqueue (matching at enqueue time). | `gateway.py` | Tests §13.1 (1–4). |
| 6 | `gateway.py` (part 2): DLQ inspect, `redrive`, `purge_dead`, `stats`. | `gateway.py` | Tests §13.4 (13–16), metrics present. |
| 7 | `worker.py`: tick loop, claim, backoff scheduling, POST, state transitions, stale-`IN_FLIGHT` reclaim, reconciliation pass on start. | `worker.py` | Tests §13.2, §13.5 (5–9, 17–20). |
| 8 | Wire `WebhookGateway(store)` + `DeliveryWorker(gw).start()`; expose `__init__.py` exports; add a short README section in `bench/P1/` for operators/receivers. | `__init__.py`, README | End-to-end test: real store + fake sender full lifecycle. |
| 9 | Full test suite green; confirm original 6 tests still pass; run under `python3 -m pytest -q`. | — | 100% pass, no new third-party imports. |
| 10 | (Optional, post-merge) Receiver guide + secret rotation docs. | docs | N/A |

**Suggested commit cadence:** one commit per row (or per 2–3 related rows),
each with tests. This keeps the diff reviewable and bisectable.

---

## 15. Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|:----------:|:------:|-----------|
| **Unbounded backlog growth** if a receiver is down for long | High | Med | `oldest_pending_age_seconds` metric + alert (§12.3); operator can disable the endpoint to stop enqueuing (§6.3); optional per-endpoint backlog cap (future knob, default off). |
| **Duplicate delivery** after crash/5xx (at-least-once) | Certain | Low (by design) | Receiver idempotency via stable key (§7); documented; receivers *must* de-dup. |
| **Thundering herd** on mass retry (many records back off together) | Med | Med | Full jitter (§5) spreads retries; bounded worker pool. |
| **Secret leak** → forged webhooks | Med | High | Per-endpoint secrets (blast-radius limited); constant-time verify; `±5 min` replay window; rotation API (§8). |
| **Clock skew** breaks signature verify | Med | Med | Replay window uses integer-seconds timestamp with ±5 min skew tolerance (§8); document NTP requirement. |
| **SQLite contention** under high append rate | Low | Med | Single writer via `threading.Lock`; WAL mode (`PRAGMA journal_mode=WAL`) recommended; one process per store by design. |
| **Reconciliation cost** on huge stores | Low | Med | Runs once per start, O(events-since-cursor) using `read_all(after_position=cursor)`; cheap for in-process scale; index on `(endpoint_id, position)` bounds the dup-check. |
| **Silent drop of an event** (the cardinal sin) | Low | High | Durable outbox written *before* `append` returns (§10.1) + gap reconciliation on every start (§10.2) + `reconcile_enqueued_total` metric to detect if it ever fires. |
| **Redirect to unexpected host** (open-redirect / SSRF-ish) | Low | Med | We do **not** follow redirects; `3xx` is retryable, not followed (§6.2). |
| **Overlapping re-drive while original still pending** | Low | Low | Re-drive only targets `DEAD` (terminal) rows, never `PENDING`/`IN_FLIGHT`/`RETRY`; unique index prevents double-enqueue. |
| **Breaking existing behaviour** | Low | High | We touch **no** existing files; all new code is additive; the 6 existing tests are a regression gate. |

---

## 16. Open questions (for the implementer to confirm, none block the plan)

1. **Backlog cap:** should a per-endpoint max-outbox depth exist (default off)?
   Recommended: off for v1; add as an operator knob later.
2. **Two-secret rotation grace period:** v1 rotates by replace; a
   dual-secret grace window is a clean future extension. Confirm scope.
3. **Fan-out mode per endpoint:** default is per-endpoint serial delivery
   (§9.1) for strict per-endpoint in-order delivery. The
   `per_endpoint_serial = False` opt-in lets a given endpoint fan out across
   the worker pool (throughput in exchange for ordering). Confirm this
   default-and-knob shape is acceptable; it is deliberately not a global
   setting so ordering-sensitive receivers keep their guarantee.
4. **Retention of `DELIVERED` rows:** default keep-all (no auto-purge);
   confirm an operator purge policy is acceptable to add later.

---

## 17. Summary

We add **outbound webhook delivery** to the event store via an **outbox +
background worker** attached to the store's existing `subscribe()` API — no
changes to existing files. Delivery is **durable** (SQLite), **at-least-once**
with **exponential backoff + full jitter** (base 5 s, ×2, cap 30 min, 6
attempts), **in-order per endpoint** (serial by default, fan-out opt-in),
**idempotent** at the receiver via a stable `wh-v1-<endpoint>-<event>`
key, and **verifiable** via per-endpoint HMAC-SHA256
(`Webhook-Signature: v1=…`). Failed deliveries land in a **DLQ** (in-place
`DEAD` state) with a safe, idempotent **re-drive**. Crash recovery is closed
by stale-`IN_FLIGHT` reclaim and a startup **reconciliation pass** that
re-enqueues any matching event missing from the outbox. The whole feature is
additive, stdlib-only, and fully covered by a deterministic,
fake-clock/fake-sender test suite.
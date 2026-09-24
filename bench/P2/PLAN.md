# P2 Plan — Webhook delivery for the event store

Goal: add `eventstore/webhooks.py` implementing a polling webhook dispatcher on
top of the existing `EventStore`. No changes to the existing store API; the
dispatcher never sleeps — time only advances through the injected `clock`.

## 1. Components

- **`Delivery`** — a `@dataclass` record for one (subscription, event) pair that
  must be POSTed. Fields exactly as in the spec:
  `id, subscription_id, event_position, idempotency_key, attempts,
  next_attempt_at, status, last_status, last_error`.
- **`WebhookDispatcher`** —
  `WebhookDispatcher(store, transport, *, clock=time.time, max_attempts=5,
  base_delay=1.0, max_delay=300.0)`.

  - `store`: any object with `head_position` and `read_all(after_position=...)`
    (the `EventStore` satisfies this).
  - `transport(url, body, headers) -> int`: one HTTP POST; returns the status
    code or raises on network error.
  - `clock() -> float`: injectable clock.

## 2. Data model (in-memory, all in the dispatcher)

- `subscriptions: dict[str, Subscription]` where `Subscription` holds
  `url`, `event_types` (`None` = all, else a `frozenset` of exact type names),
  `secret` (str or None), and `since_position` — the store's `head_position`
  captured at `subscribe()` time.
- `deliveries: list[Delivery]` — append-only creation order; `status` moves
  `pending -> delivered` / `pending -> dead` / `dead -> pending` (redrive).
- `delivered_by_sub` bookkeeping is implicit via each delivery's
  `subscription_id`; unsubscribe removes only that subscription's `pending`
  entries, keeping its `delivered`/`dead` records.
- Dedup key: `set[(subscription_id, event_position)]` — an event is never
  enqueued twice for the same subscription.
- ID generation: `uuid.uuid4().hex` for subscription and delivery ids
  (unique, opaque). Idempotency key: `f"{subscription_id}:{event.id}"`
  (event id = the store-assigned hex id of the `Event`).

## 3. Behaviour and state transitions

### subscribe / unsubscribe
- `subscribe(url, *, event_types=None, secret=None)`:
  - `ValueError` if `url` is empty (falsy after stripping is treated as empty;
    spec says "empty url" → reject `url` that is `""`; non-str also rejected).
  - `event_types=None` → all types; otherwise stored as a set for exact match.
  - Records `since_position = store.head_position`. Returns the new id.
- `unsubscribe(subscription_id)`:
  - `KeyError` if unknown.
  - Deletes the subscription and **drops its pending deliveries** (they are
    neither attempted nor dead-lettered); delivered/dead records for it stay.

### poll()
- Reads `store.read_all(after_position=last_poll_position)` (cursor starts at
  the dispatcher's own initial head; per event, only subscriptions with
  `since_position < event.position` and matching type get a delivery).
- Each new delivery: `status="pending"`, `attempts=0`,
  `next_attempt_at=clock()`, `last_status=None`, `last_error=None`.
- Returns count created; idempotent — no new events ⇒ 0.

### run_due()
- Selects pending deliveries with `next_attempt_at <= clock()`, ordered by
  `(next_attempt_at, creation order)`; attempts each **at most once**.
- Per attempt:
  - `body = json.dumps(event.to_dict(), sort_keys=True, separators=(",",":")).encode()`
  - headers: `Content-Type: application/json`;
    `Idempotency-Key: <sub_id>:<event id>` (stable, survives redrive);
    `X-Webhook-Event: <type>`;
    `X-Webhook-Signature: sha256=<hmac_sha256(body, secret.encode()).hexdigest()>`
    only when the subscription has a secret.
  - `attempts += 1`; call transport.
- Outcome (after incrementing `attempts`):
  - transport exception → retryable: `last_status=None`,
    `last_error=str(e)` (ensure non-empty; if `str(e)` is empty, fall back to
    the exception class name).
  - `2xx` → `status="delivered"`, `last_error=None`.
  - retryable status (`408`, `429`, any `5xx`) →
    if `attempts >= max_attempts` → `dead`; else stays `pending` with
    `next_attempt_at = clock() + min(max_delay, base_delay * 2**(attempts-1))`.
  - any other status (1xx/3xx/other 4xx) → `dead` immediately (permanent).
  - On every failure `last_error` is a non-empty string (e.g. `"HTTP 503"`).
- Returns number of attempts made.

### dead-letter queue
- `dead_letters()` → snapshot list of dead deliveries, creation order.
- `redrive(delivery_id)`:
  - unknown id → `KeyError`; delivery not `dead` → `ValueError`.
  - Resets `status="pending"`, `attempts=0`, `next_attempt_at=clock()`,
    `last_status=None`, `last_error=None`; keeps `id`, `idempotency_key`,
    `subscription_id`, `event_position`.

### Snapshots
- `pending()`, `delivered()`, `dead_letters()` return new lists in creation
  order.

### Validation
- `__init__`: `max_attempts < 1`, `base_delay < 0`, `max_delay < 0` →
  `ValueError`.

## 4. Edge cases / design decisions

- **1xx/3xx** are "permanent → dead" per spec ("any other status").
- **Retryable backoff** uses the post-increment `attempts` (1-based): first
  retry waits `base_delay`, then `2*base_delay`, … capped at `max_delay`.
- **Redrive after a permanent failure**: allowed — attempts reset, so the
  same URL is retried fresh; the idempotency key lets receivers dedupe.
- **Unsubscribed subscription with pending deliveries**: dropped silently.
- **Clock only via injection**: `poll()`/`run_due()`/`redrive()` call
  `self._clock()`; no `time.sleep` anywhere.
- **`event_types` matching** is exact string equality against `Event.type`.
- **Delivery lookup by id** uses a dict index for O(1); the ordered list is
  kept as the source of truth for creation order.

## 5. Test plan (`tests/test_webhooks.py`)

Fake transport + controllable clock, small `EventStore` with deterministic ids
(`id_factory`), covering:

1. subscribe/unsubscribe (unique ids, unknown unsubscribe → KeyError).
2. only events *after* subscribe position are delivered; `event_types` filter;
   no filter = all types.
3. poll idempotency (second poll → 0); due-immediately; `attempts=0`.
4. request shape: exact body (sorted, compact JSON), all four headers,
   signature only when secret set, and the HMAC value is verified in-test.
5. 2xx → delivered (last_error None); 408/429/5xx → pending with exponential
   backoff base, 2·base, 4·base … capped at max_delay; `attempts` increments.
6. transport exception → retryable, `last_status=None`, `last_error` non-empty.
7. `attempts >= max_attempts` after a retryable failure → dead.
8. permanent (e.g. 400) → dead immediately.
9. ordering: oldest `next_attempt_at` first, then creation order; one attempt
   per delivery per `run_due()`.
10. dead_letters + redrive (same id/key, attempts 0, due now; unknown →
    KeyError; non-dead → ValueError).
11. unsubscribe discards pending, keeps delivered/dead.
12. validation: `max_attempts<1`, negative delays, empty url → ValueError.
13. existing store tests still pass (no API changes).

Run: `cd bench/P2 && python3 -m pytest -q`.
# P2 — Plan and implement webhook delivery for the event store

Work only inside `bench/P2/`. `bench/P2/src/eventstore/` is a minimal
append-only event store (read `store.py` and `events.py` first). Run tests with
`cd bench/P2 && python3 -m pytest -q` (the `conftest.py` puts `src/` on the
import path). Python standard library only (plus pytest for tests).

## Steps

1. **Plan first.** Write `bench/P2/PLAN.md` (design, data model, state
   transitions, test plan) *before* writing the implementation.
2. **Implement** the feature below in a new module
   `bench/P2/src/eventstore/webhooks.py`. Do not change the behaviour of the
   existing `EventStore` API; existing tests must keep passing.
3. **Test** it: add `bench/P2/tests/test_webhooks.py` covering the spec.

Your implementation will also be graded by a hidden test suite written
against the exact interface below, so follow names, signatures, defaults and
rules precisely.

## Specification

### Interface (`eventstore/webhooks.py`)

```python
@dataclass
class Delivery:
    id: str                       # unique, opaque
    subscription_id: str
    event_position: int           # Event.position being delivered
    idempotency_key: str
    attempts: int                 # attempts made so far
    next_attempt_at: float        # clock() time when next due
    status: str                   # "pending" | "delivered" | "dead"
    last_status: int | None       # last HTTP status seen, None if none / exception
    last_error: str | None        # description of the last failure, None if none

class WebhookDispatcher:
    def __init__(self, store, transport, *, clock=time.time,
                 max_attempts=5, base_delay=1.0, max_delay=300.0): ...
    def subscribe(self, url, *, event_types=None, secret=None) -> str: ...
    def unsubscribe(self, subscription_id) -> None: ...
    def poll(self) -> int: ...
    def run_due(self) -> int: ...
    def pending(self) -> list[Delivery]: ...
    def delivered(self) -> list[Delivery]: ...
    def dead_letters(self) -> list[Delivery]: ...
    def redrive(self, delivery_id) -> None: ...
```

`transport(url: str, body: bytes, headers: dict[str, str]) -> int` performs one
HTTP POST and returns the status code, or raises any exception on a network
error. `clock()` returns the current time in float seconds. The dispatcher
never sleeps; time only advances through `clock`.

### Rules

1. **Subscriptions.** `subscribe` returns a new unique subscription id. A
   subscription receives only events whose `position` is greater than the
   store's `head_position` at the moment it subscribed. `event_types=None`
   means all event types; otherwise an iterable of type names to match
   exactly. `unsubscribe` of an unknown id raises `KeyError`.
2. **Polling.** `poll()` reads events from the store that it has not yet
   processed and creates one `pending` delivery per (matching subscription,
   event), due immediately (`next_attempt_at = clock()`, `attempts = 0`). It
   returns the number of deliveries created. Calling `poll()` again without
   new events creates nothing — an event is never enqueued twice for the same
   subscription.
3. **Request.** Each attempt calls `transport(url, body, headers)` with
   - `body` = `json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":")).encode()`
   - headers:
     - `Content-Type: application/json`
     - `Idempotency-Key: <subscription_id>:<event id>` — identical on every
       attempt of that delivery, including after a redrive
     - `X-Webhook-Event: <event type>`
     - `X-Webhook-Signature: sha256=<hex HMAC-SHA256 of body keyed with
       secret.encode()>` — only when the subscription has a `secret`
4. **Running.** `run_due()` attempts every `pending` delivery whose
   `next_attempt_at <= clock()`, oldest first (by `next_attempt_at`, then
   creation order). Each delivery is attempted **at most once per
   `run_due()` call**. Returns the number of attempts made.
5. **Outcomes.** After each attempt `attempts` increases by 1 and
   `last_status` is set to the status code (or `None` if the transport
   raised).
   - `2xx` → `delivered`; `last_error = None`.
   - **Retryable**: transport exception, `408`, `429`, any `5xx`.
     If `attempts >= max_attempts` → `dead`. Otherwise stays `pending` with
     `next_attempt_at = clock() + min(max_delay, base_delay * 2 ** (attempts - 1))`
     (i.e. base, 2·base, 4·base, … capped at `max_delay`).
   - **Any other status** (1xx, 3xx, other 4xx) is permanent → `dead`
     immediately.
   - On every failure `last_error` is a non-empty string (the exception
     text, or e.g. `"HTTP 503"`).
6. **Dead-letter queue.** `dead_letters()` returns the dead deliveries.
   `redrive(delivery_id)` moves a dead delivery back to `pending` with
   `attempts = 0`, due immediately, same `id` and same `idempotency_key`.
   Redriving an unknown id raises `KeyError`; redriving a delivery that is
   not dead raises `ValueError`.
7. **Unsubscribe** discards that subscription's `pending` deliveries (they
   are not dead-lettered and never attempted again); its `delivered` and
   `dead` records are kept.
8. `pending()`, `delivered()`, `dead_letters()` return lists (snapshots)
   ordered by creation order.
9. Validation: `max_attempts < 1`, negative `base_delay`/`max_delay`, or an
   empty `url` raise `ValueError`.

"""Polling webhook delivery on top of the append-only event store.

`WebhookDispatcher` watches an `EventStore` for new events and fans them out
to HTTP endpoints ("subscriptions"). It never sleeps: all timing comes from
an injectable `clock`, and all HTTP from an injectable `transport`.
Deliveries retry with capped exponential backoff and land in a dead-letter
queue once the retry budget is exhausted or a permanent (non-retryable)
status is returned.

See ``TASK.md`` for the full specification and ``PLAN.md`` for the design.
"""

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass


@dataclass
class Delivery:
    """One (subscription, event) unit of work to POST to an endpoint."""

    id: str                       # unique, opaque
    subscription_id: str
    event_position: int           # Event.position being delivered
    idempotency_key: str
    attempts: int                 # attempts made so far
    next_attempt_at: float        # clock() time when next due
    status: str                   # "pending" | "delivered" | "dead"
    last_status: int | None       # last HTTP status seen, None if none / exception
    last_error: str | None        # description of the last failure, None if none


@dataclass
class _Subscription:
    """A registered webhook endpoint and what it wants to receive."""

    id: str
    url: str
    event_types: frozenset | None  # None = all event types
    secret: str | None
    since_position: int            # store head_position at subscribe() time


def _body_for(event) -> bytes:
    """Canonical JSON body for one event (sorted keys, compact separators)."""
    return json.dumps(
        event.to_dict(), sort_keys=True, separators=(",", ":")
    ).encode()


class WebhookDispatcher:
    def __init__(
        self,
        store,
        transport,
        *,
        clock=time.time,
        max_attempts=5,
        base_delay=1.0,
        max_delay=300.0,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if base_delay < 0:
            raise ValueError("base_delay must be >= 0")
        if max_delay < 0:
            raise ValueError("max_delay must be >= 0")

        self._store = store
        self._transport = transport
        self._clock = clock
        self._max_attempts = max_attempts
        self._base_delay = base_delay
        self._max_delay = max_delay

        self._subscriptions: dict[str, _Subscription] = {}
        self._deliveries: list[Delivery] = []   # creation order (source of truth)
        self._by_id: dict[str, Delivery] = {}
        self._enqueued: set[tuple[str, int]] = set()   # (sub_id, event_position)
        # Events already in the store are not replayed; poll() only looks at
        # events appended after the last poll (per-subscription filtering via
        # since_position still applies on top of this).
        self._poll_position = store.head_position

    # -- subscriptions ------------------------------------------------------

    def subscribe(self, url, *, event_types=None, secret=None) -> str:
        """Register a webhook endpoint; returns a new unique subscription id."""
        if not url:
            raise ValueError("url must be a non-empty string")
        sub_id = uuid.uuid4().hex
        if event_types is None:
            types = None
        elif isinstance(event_types, str):
            types = frozenset({event_types})
        else:
            types = frozenset(event_types)
        self._subscriptions[sub_id] = _Subscription(
            id=sub_id,
            url=url,
            event_types=types,
            secret=secret,
            since_position=self._store.head_position,
        )
        return sub_id

    def unsubscribe(self, subscription_id) -> None:
        if subscription_id not in self._subscriptions:
            raise KeyError(subscription_id)
        del self._subscriptions[subscription_id]
        # Discard that subscription's pending deliveries (not dead-lettered and
        # never attempted again); its delivered/dead records are kept.
        for delivery in list(self._deliveries):
            if (
                delivery.subscription_id == subscription_id
                and delivery.status == "pending"
            ):
                self._drop(delivery)

    def _drop(self, delivery: Delivery) -> None:
        self._deliveries.remove(delivery)
        self._by_id.pop(delivery.id, None)
        self._enqueued.discard((delivery.subscription_id, delivery.event_position))

    # -- enqueue ------------------------------------------------------------

    def poll(self) -> int:
        """Enqueue pending deliveries for new events; returns how many created.

        Idempotent: an event is never enqueued twice for the same
        subscription, so calling poll() again without new events creates
        nothing.
        """
        events = self._store.read_all(after_position=self._poll_position)
        created = 0
        for event in events:
            for sub in self._subscriptions.values():
                if event.position <= sub.since_position:
                    continue
                if sub.event_types is not None and event.type not in sub.event_types:
                    continue
                if (sub.id, event.position) in self._enqueued:
                    continue
                self._create_delivery(sub, event)
                created += 1
        if events:
            self._poll_position = events[-1].position
        return created

    def _create_delivery(self, sub: _Subscription, event) -> None:
        delivery = Delivery(
            id=uuid.uuid4().hex,
            subscription_id=sub.id,
            event_position=event.position,
            idempotency_key=f"{sub.id}:{event.id}",
            attempts=0,
            next_attempt_at=float(self._clock()),
            status="pending",
            last_status=None,
            last_error=None,
        )
        self._deliveries.append(delivery)
        self._by_id[delivery.id] = delivery
        self._enqueued.add((sub.id, event.position))

    # -- run ----------------------------------------------------------------

    def run_due(self) -> int:
        """Attempt every due pending delivery (at most once each); returns the
        number of attempts made.

        Due means ``next_attempt_at <= clock()``; attempts happen oldest
        ``next_attempt_at`` first, then creation order.
        """
        now = float(self._clock())
        due = [
            d
            for d in self._deliveries
            if d.status == "pending"
            and d.next_attempt_at <= now
            and d.subscription_id in self._subscriptions
        ]
        # Stable sort: ties on next_attempt_at keep creation order.
        due.sort(key=lambda d: d.next_attempt_at)
        attempts = 0
        for delivery in due:
            self._execute(delivery)
            attempts += 1
        return attempts

    def _execute(self, delivery: Delivery) -> None:
        sub = self._subscriptions[delivery.subscription_id]
        event = self._find_event(delivery)
        body = _body_for(event)
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": delivery.idempotency_key,
            "X-Webhook-Event": event.type,
        }
        if sub.secret is not None:
            signature = hmac.new(sub.secret.encode(), body, hashlib.sha256).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={signature}"

        delivery.attempts += 1
        error: str | None = None
        try:
            status = self._transport(sub.url, body, headers)
        except Exception as exc:  # noqa: BLE001 - transport network error
            status = None
            error = str(exc) or type(exc).__name__

        if error is not None:
            self._fail(delivery, status, error)
        elif 200 <= status < 300:
            delivery.status = "delivered"
            delivery.last_status = status
            delivery.last_error = None
        elif self._retryable(status):
            self._fail(delivery, status, f"HTTP {status}")
        else:
            # Permanent: 1xx, 3xx, and non-retryable 4xx dead-letter
            # immediately.
            delivery.status = "dead"
            delivery.last_status = status
            delivery.last_error = f"HTTP {status}"

    @staticmethod
    def _retryable(status: int) -> bool:
        return status in (408, 429) or 500 <= status < 600

    def _fail(self, delivery: Delivery, status: int | None, error: str) -> None:
        delivery.last_status = status
        delivery.last_error = error
        if delivery.attempts >= self._max_attempts:
            delivery.status = "dead"
            return
        delay = min(
            self._max_delay, self._base_delay * 2 ** (delivery.attempts - 1)
        )
        delivery.next_attempt_at = float(self._clock()) + delay

    def _find_event(self, delivery: Delivery):
        for event in self._store.read_all(after_position=0):
            if event.position == delivery.event_position:
                return event
        raise LookupError(
            f"event at position {delivery.event_position} no longer in store"
        )

    # -- dead-letter queue --------------------------------------------------

    def redrive(self, delivery_id) -> None:
        """Move a dead delivery back to pending, due immediately.

        The retry budget restarts; the id and idempotency key are preserved.
        Unknown id raises KeyError; a non-dead delivery raises ValueError.
        """
        delivery = self._by_id.get(delivery_id)
        if delivery is None:
            raise KeyError(delivery_id)
        if delivery.status != "dead":
            raise ValueError(delivery_id)
        delivery.status = "pending"
        delivery.attempts = 0
        delivery.next_attempt_at = float(self._clock())
        delivery.last_status = None
        delivery.last_error = None

    # -- snapshots ----------------------------------------------------------

    def pending(self) -> list[Delivery]:
        return [d for d in self._deliveries if d.status == "pending"]

    def delivered(self) -> list[Delivery]:
        return [d for d in self._deliveries if d.status == "delivered"]

    def dead_letters(self) -> list[Delivery]:
        return [d for d in self._deliveries if d.status == "dead"]
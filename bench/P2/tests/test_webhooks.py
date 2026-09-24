"""Tests for `eventstore.webhooks` (see ``TASK.md`` and ``PLAN.md``)."""

import hashlib
import hmac
import json

import pytest

from eventstore import EventStore
from eventstore.webhooks import WebhookDispatcher


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class Clock:
    """Manual, deterministic clock (no real time passes)."""

    def __init__(self, t=1000.0):
        self.t = float(t)

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class Transport:
    """Records calls and returns a fixed status code."""

    def __init__(self, status=200):
        self.status = status
        self.calls = []

    def __call__(self, url, body, headers):
        self.calls.append((url, body, headers))
        return self.status


class RaisingTransport:
    """Raises on every call (simulates a network error)."""

    def __init__(self, exc):
        self.exc = exc
        self.calls = []

    def __call__(self, url, body, headers):
        self.calls.append((url, body, headers))
        raise self.exc


def make_store(clock):
    counter = iter(range(1, 10_000))
    return EventStore(clock=lambda: clock(), id_factory=lambda: f"e{next(counter)}")


def make():
    """A (Clock, EventStore) pair wired to the same clock."""
    ck = Clock()
    return ck, make_store(ck)


def positions(calls):
    """Event positions in the order they were POSTed by `calls`."""
    return [json.loads(body)["position"] for (_url, body, _headers) in calls]


def dispatch(store, transport, clock, **kwargs):
    return WebhookDispatcher(store, transport, clock=clock, **kwargs)


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


def test_subscribe_returns_unique_ids():
    ck, store = make()
    d = dispatch(store, Transport(), ck)
    a, b = d.subscribe("http://a"), d.subscribe("http://b")
    assert a != b and a and b


def test_subscribe_rejects_empty_url():
    ck, store = make()
    d = dispatch(store, Transport(), ck)
    with pytest.raises(ValueError):
        d.subscribe("")


def test_unsubscribe_unknown_raises_keyerror():
    ck, store = make()
    d = dispatch(store, Transport(), ck)
    with pytest.raises(KeyError):
        d.unsubscribe("does-not-exist")


def test_only_events_after_subscribe_are_delivered():
    ck, store = make()
    d = dispatch(store, Transport(), ck)
    store.append("s1", "T")                 # present before subscribing
    sid = d.subscribe("http://x")
    e1 = store.append("s1", "T")
    assert d.poll() == 1
    d.run_due()
    assert len(d.delivered()) == 1
    assert d.delivered()[0].event_position == e1.position
    assert d.delivered()[0].subscription_id == sid


def test_event_types_filter():
    ck, store = make()
    tr = Transport()
    d = dispatch(store, tr, ck)
    d.subscribe("http://x", event_types={"Alpha"})
    store.append("s", "Alpha")
    store.append("s", "Beta")
    assert d.poll() == 1
    d.run_due()
    assert len(d.delivered()) == 1
    assert json.loads(tr.calls[0][1])["type"] == "Alpha"


def test_no_filter_delivers_all_types():
    ck, store = make()
    d = dispatch(store, Transport(), ck)
    d.subscribe("http://x")
    store.append("s", "A")
    store.append("s", "B")
    assert d.poll() == 2


def test_multiple_subscriptions_fan_out():
    ck, store = make()
    d = dispatch(store, Transport(), ck)
    d.subscribe("http://a")
    d.subscribe("http://b")
    store.append("s", "T")
    assert d.poll() == 2
    d.run_due()
    assert len(d.delivered()) == 2


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------


def test_poll_is_idempotent():
    ck, store = make()
    d = dispatch(store, Transport(), ck)
    d.subscribe("http://x")
    store.append("s", "T")
    assert d.poll() == 1
    assert d.poll() == 0
    assert d.poll() == 0


def test_poll_creates_pending_due_now_with_zero_attempts():
    ck, store = make()
    d = dispatch(store, Transport(), ck)
    d.subscribe("http://x")
    store.append("s", "T")
    d.poll()
    p = d.pending()[0]
    assert p.status == "pending"
    assert p.attempts == 0
    assert p.next_attempt_at == ck()
    assert p.last_status is None
    assert p.last_error is None


# ---------------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------------


def test_request_body_and_headers_without_secret():
    ck, store = make()
    tr = Transport()
    d = dispatch(store, tr, ck)
    sid = d.subscribe("http://x")
    e = store.append("s", "OrderPlaced", {"total": 5})
    d.poll()
    d.run_due()
    url, body, headers = tr.calls[0]
    assert url == "http://x"
    expected = json.dumps(e.to_dict(), sort_keys=True, separators=(",", ":")).encode()
    assert body == expected
    assert headers["Content-Type"] == "application/json"
    assert headers["Idempotency-Key"] == f"{sid}:{e.id}"
    assert headers["X-Webhook-Event"] == "OrderPlaced"
    assert "X-Webhook-Signature" not in headers


def test_signature_only_when_secret_set():
    ck, store = make()
    tr = Transport()
    d = dispatch(store, tr, ck)
    secret = "s3cr3t"
    d.subscribe("http://x", secret=secret)
    store.append("s", "T", {"k": "v"})
    d.poll()
    d.run_due()
    _url, body, headers = tr.calls[0]
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert headers["X-Webhook-Signature"] == expected


def test_idempotency_key_stable_across_attempts():
    ck, store = make()
    tr = Transport(503)
    d = dispatch(store, tr, ck, max_attempts=10, base_delay=1.0)
    d.subscribe("http://x")
    store.append("s", "T")
    d.poll()
    for _ in range(3):
        d.run_due()
        ck.advance(100.0)
    assert len({h["Idempotency-Key"] for (_u, _b, h) in tr.calls}) == 1


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


def test_2xx_delivered():
    ck, store = make()
    d = dispatch(store, Transport(201), ck)
    d.subscribe("http://x")
    store.append("s", "T")
    d.poll()
    d.run_due()
    dl = d.delivered()[0]
    assert dl.status == "delivered"
    assert dl.last_status == 201
    assert dl.last_error is None


def test_retryable_backoff_sequence():
    ck, store = make()
    d = dispatch(store, Transport(503), ck, max_attempts=10, base_delay=2.0, max_delay=100.0)
    d.subscribe("http://x")
    store.append("s", "T")
    d.poll()

    t0 = ck()
    assert d.run_due() == 1
    p = d.pending()[0]
    assert p.attempts == 1
    assert p.last_status == 503
    assert p.last_error == "HTTP 503"
    assert p.next_attempt_at == t0 + 2.0          # base * 2**0

    assert d.run_due() == 0                        # not due yet
    ck.advance(2.0)
    t1 = ck()
    assert d.run_due() == 1
    p = d.pending()[0]
    assert p.attempts == 2
    assert p.next_attempt_at == t1 + 4.0           # base * 2**1

    ck.advance(4.0)
    t2 = ck()
    assert d.run_due() == 1
    p = d.pending()[0]
    assert p.attempts == 3
    assert p.next_attempt_at == t2 + 8.0           # base * 2**2


def test_backoff_capped_at_max_delay():
    ck, store = make()
    d = dispatch(store, Transport(503), ck, max_attempts=10, base_delay=10.0, max_delay=15.0)
    d.subscribe("http://x")
    store.append("s", "T")
    d.poll()

    t0 = ck()
    d.run_due()
    assert d.pending()[0].next_attempt_at == t0 + 10.0   # min(15, 10)

    ck.advance(10.0)
    t1 = ck()
    d.run_due()
    assert d.pending()[0].next_attempt_at == t1 + 15.0   # min(15, 20) -> 15


def test_transport_exception_is_retryable():
    ck, store = make()
    d = dispatch(
        store,
        RaisingTransport(ConnectionError("boom")),
        ck,
        max_attempts=10,
        base_delay=1.0,
    )
    d.subscribe("http://x")
    store.append("s", "T")
    d.poll()
    t0 = ck()
    assert d.run_due() == 1
    p = d.pending()[0]
    assert p.attempts == 1
    assert p.last_status is None
    assert p.last_error == "boom"
    assert p.next_attempt_at == t0 + 1.0


def test_dead_after_max_attempts():
    ck, store = make()
    d = dispatch(store, Transport(500), ck, max_attempts=3, base_delay=1.0)
    d.subscribe("http://x")
    store.append("s", "T")
    d.poll()
    for _ in range(3):
        d.run_due()
        ck.advance(100.0)
    assert len(d.dead_letters()) == 1
    assert d.dead_letters()[0].status == "dead"
    assert d.dead_letters()[0].attempts == 3
    assert d.pending() == []
    assert d.run_due() == 0


@pytest.mark.parametrize("status", (408, 429))
def test_408_and_429_are_retryable(status):
    ck, store = make()
    d = dispatch(store, Transport(status), ck, max_attempts=5, base_delay=1.0)
    d.subscribe("http://x")
    store.append("s", "T")
    d.poll()
    assert d.run_due() == 1
    assert len(d.pending()) == 1          # still pending, not dead


def test_non_retryable_4xx_is_permanent():
    ck, store = make()
    d = dispatch(store, Transport(404), ck, max_attempts=5, base_delay=1.0)
    d.subscribe("http://x")
    store.append("s", "T")
    d.poll()
    assert d.run_due() == 1
    dl = d.dead_letters()[0]
    assert dl.status == "dead"
    assert dl.attempts == 1
    assert dl.last_status == 404
    assert dl.last_error == "HTTP 404"
    assert d.pending() == []


# ---------------------------------------------------------------------------
# Ordering / at-most-once
# ---------------------------------------------------------------------------


def test_run_due_oldest_first_then_creation_order():
    ck, store = make()
    tr = Transport(500)                    # keeps everything pending
    d = dispatch(store, tr, ck, max_attempts=10, base_delay=10.0)
    d.subscribe("http://x")
    e1 = store.append("s", "A")
    d.poll()                                # due at t0
    ck.advance(5.0)
    e2 = store.append("s", "B")
    d.poll()                                # due at t5
    assert d.run_due() == 2
    assert positions(tr.calls) == [e1.position, e2.position]


def test_run_due_at_most_once_per_call():
    ck, store = make()
    tr = Transport(503)
    d = dispatch(store, tr, ck, max_attempts=10, base_delay=0.0)
    d.subscribe("http://x")
    store.append("s", "T")
    d.poll()
    assert d.run_due() == 1                # due again (delay 0) but one per call
    assert d.run_due() == 1
    assert len(tr.calls) == 2


# ---------------------------------------------------------------------------
# Dead-letter queue
# ---------------------------------------------------------------------------


def test_redrive():
    ck, store = make()
    tr = Transport(500)
    d = dispatch(store, tr, ck, max_attempts=1, base_delay=1.0)
    d.subscribe("http://x")
    store.append("s", "T")
    d.poll()
    d.run_due()                            # attempts(1) >= max(1) -> dead
    dl = d.dead_letters()[0]
    orig_id, orig_key = dl.id, dl.idempotency_key
    t0 = ck()
    d.redrive(orig_id)
    p = d.pending()[0]
    assert p.id == orig_id
    assert p.idempotency_key == orig_key
    assert p.attempts == 0
    assert p.status == "pending"
    assert p.next_attempt_at == t0
    assert p.last_status is None and p.last_error is None
    assert d.run_due() == 1                # due immediately after redrive


def test_redrive_unknown_raises_keyerror():
    ck, store = make()
    d = dispatch(store, Transport(), ck)
    with pytest.raises(KeyError):
        d.redrive("nope")


def test_redrive_non_dead_raises_valueerror():
    ck, store = make()
    d = dispatch(store, Transport(200), ck)
    d.subscribe("http://x")
    store.append("s", "T")
    d.poll()
    with pytest.raises(ValueError):
        d.redrive(d.pending()[0].id)       # pending, not dead


# ---------------------------------------------------------------------------
# Unsubscribe semantics
# ---------------------------------------------------------------------------


def test_unsubscribe_discards_pending_keeps_delivered():
    ck, store = make()
    d = dispatch(store, Transport(200), ck)
    sid = d.subscribe("http://x")
    store.append("s", "T")
    d.poll()
    d.run_due()
    assert len(d.delivered()) == 1

    store.append("s", "T")
    d.poll()
    assert len(d.pending()) == 1

    d.unsubscribe(sid)
    assert d.pending() == []               # pending discarded
    assert len(d.delivered()) == 1         # delivered kept
    store.append("s", "T")
    assert d.poll() == 0                   # gone: no further deliveries


def test_unsubscribe_keeps_dead_records():
    ck, store = make()
    d = dispatch(store, Transport(400), ck)   # permanent -> dead
    sid = d.subscribe("http://x")
    store.append("s", "T")
    d.poll()
    d.run_due()
    assert len(d.dead_letters()) == 1
    d.unsubscribe(sid)
    assert len(d.dead_letters()) == 1        # dead kept
    assert d.pending() == []


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_rejects_max_attempts_below_one():
    ck, store = make()
    with pytest.raises(ValueError):
        dispatch(store, Transport(), ck, max_attempts=0)


def test_rejects_negative_delays():
    ck, store = make()
    with pytest.raises(ValueError):
        dispatch(store, Transport(), ck, base_delay=-1.0)
    with pytest.raises(ValueError):
        dispatch(store, Transport(), ck, max_delay=-1.0)


def test_snapshots_are_lists_in_creation_order():
    ck, store = make()
    d = dispatch(store, Transport(200), ck)
    d.subscribe("http://x")
    for i in range(3):
        store.append("s", f"T{i}")
    d.poll()
    snap = d.pending()
    assert isinstance(snap, list)
    assert [p.event_position for p in snap] == [1, 2, 3]
    # Mutating the snapshot does not affect the dispatcher's state.
    snap.clear()
    assert len(d.pending()) == 3


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", (100, 301))
def test_1xx_and_3xx_are_permanent(status):
    ck, store = make()
    d = dispatch(store, Transport(status), ck, max_attempts=5, base_delay=1.0)
    d.subscribe("http://x")
    store.append("s", "T")
    d.poll()
    assert d.run_due() == 1
    dl = d.dead_letters()[0]
    assert dl.status == "dead"
    assert dl.attempts == 1
    assert dl.last_status == status


def test_all_5xx_are_retryable():
    for status in (500, 502, 503, 504, 599):
        ck, store = make()
        d = dispatch(store, Transport(status), ck, max_attempts=5, base_delay=1.0)
        d.subscribe("http://x")
        store.append("s", "T")
        d.poll()
        d.run_due()
        assert len(d.pending()) == 1, status    # stayed pending, retryable
        assert d.dead_letters() == []


def test_poll_cursor_advances_across_cycles():
    ck, store = make()
    tr = Transport()
    d = dispatch(store, tr, ck)
    d.subscribe("http://x")
    store.append("s", "A")
    assert d.poll() == 1
    d.run_due()
    store.append("s", "B")
    assert d.poll() == 1
    d.run_due()
    # Only the two new events were delivered, in order.
    assert positions(tr.calls) == [1, 2]
    assert len(d.delivered()) == 2


def test_event_types_accepts_plain_iterable():
    ck, store = make()
    tr = Transport()
    d = dispatch(store, tr, ck)
    d.subscribe("http://x", event_types=("A", "B"))
    store.append("s", "A")
    store.append("s", "B")
    store.append("s", "C")
    assert d.poll() == 2
    d.run_due()
    assert len(d.delivered()) == 2


def test_redrive_then_deliver():
    ck, store = make()

    class Flaky:
        """Raises while down=True, else returns a fixed status."""

        def __init__(self):
            self.down = True
            self.status = 200

        def __call__(self, url, body, headers):
            if self.down:
                raise ConnectionError("down")
            return self.status

    tr = Flaky()
    d = dispatch(store, tr, ck, max_attempts=1, base_delay=1.0)
    d.subscribe("http://x")
    store.append("s", "T")
    d.poll()
    d.run_due()
    assert len(d.dead_letters()) == 1
    # Recovery: transport now healthy, redrive and deliver.
    tr.down = False
    d.redrive(d.dead_letters()[0].id)
    d.run_due()
    assert len(d.delivered()) == 1
    assert d.dead_letters() == []


def test_run_due_returns_zero_when_none_due():
    ck, store = make()
    d = dispatch(store, Transport(), ck)
    assert d.run_due() == 0
    d.subscribe("http://x")
    store.append("s", "T")
    d.poll()
    ck.advance(-10.0)                        # clock before delivery due time
    assert d.run_due() == 0

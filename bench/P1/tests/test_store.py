import pytest

from eventstore import ConcurrencyError, EventStore, EventStoreError


def ids():
    n = iter(range(1, 10_000))
    return lambda: f"e{next(n)}"


def test_append_assigns_positions_and_versions():
    s = EventStore(id_factory=ids(), clock=lambda: 100.0)
    a = s.append("order-1", "Placed", {"total": 5})
    b = s.append("order-2", "Placed")
    c = s.append("order-1", "Paid")
    assert (a.position, a.version) == (1, 1)
    assert (b.position, b.version) == (2, 1)
    assert (c.position, c.version) == (3, 2)
    assert a.id == "e1" and a.recorded_at == 100.0
    assert s.head_position == 3


def test_expected_version():
    s = EventStore()
    s.append("x", "A", expected_version=0)
    with pytest.raises(ConcurrencyError):
        s.append("x", "B", expected_version=0)
    s.append("x", "B", expected_version=1)
    assert s.stream_version("x") == 2


def test_rejects_bad_input():
    s = EventStore()
    with pytest.raises(EventStoreError):
        s.append("", "A")
    with pytest.raises(EventStoreError):
        s.append("x", "")


def test_read_stream_and_all():
    s = EventStore()
    for i in range(5):
        s.append("a" if i % 2 == 0 else "b", "T", {"i": i})
    assert [e.data["i"] for e in s.read_stream("a")] == [0, 2, 4]
    assert [e.data["i"] for e in s.read_stream("a", from_version=2)] == [2, 4]
    assert [e.position for e in s.read_all(after_position=3)] == [4, 5]
    assert [e.position for e in s.read_all(limit=2)] == [1, 2]


def test_persistence_roundtrip(tmp_path):
    p = tmp_path / "events.jsonl"
    s = EventStore(p)
    s.append("a", "T", {"k": 1})
    s.append("b", "U")
    s2 = EventStore(p)
    assert [e.to_dict() for e in s2.read_all()] == [e.to_dict() for e in s.read_all()]
    assert s2.append("a", "V").position == 3


def test_listeners_called_and_isolated():
    s = EventStore()
    seen = []

    def bad(_e):
        raise RuntimeError("boom")

    s.subscribe(bad)
    unsub = s.subscribe(seen.append)
    e = s.append("a", "T")
    assert seen == [e]
    unsub()
    s.append("a", "T")
    assert len(seen) == 1

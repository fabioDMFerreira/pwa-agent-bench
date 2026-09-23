"""Replication: shipping, ack semantics, failover replay."""

import pytest

from kve import ReplicationError
from kve.replication import Replicator
from kve.sink import MemorySink


class _FakeFrame:
    def __init__(self, payload):
        self.payload = payload
        self.offset = 0
        self.length = len(payload)


def _rep(tmp_path=None):
    sink = MemorySink()
    return Replicator(sink), sink


def test_ship_advances_ack():
    rep, sink = _rep()
    for i in range(3):
        rep.ship(_FakeFrame(f"frame-{i}".encode()))
    assert rep.shipped == 3
    assert rep.acked_seq == 2  # the last shipped frame is durably acked
    assert len(sink) == 3


def test_ack_semantics_single_frame():
    rep, _sink = _rep()
    rep.ship(_FakeFrame(b"only"))
    assert rep.acked_seq == 0


def test_replay_covers_full_acked_prefix():
    from kve.crc import encode_put

    rep, sink = _rep()
    for k in ("a", "b", "c"):
        rep.ship(_FakeFrame(encode_put(k, k.upper())))
    replayed = list(rep.replay_sink())
    assert replayed == [("put", "a", "A"), ("put", "b", "B"), ("put", "c", "C")]
    assert len(sink) == 3


def test_failover_preserves_last_write():
    """A failover must see every write up to and including the last one."""
    from kve.crc import encode_put

    rep, sink = _rep()
    for k in ("a", "b", "c"):
        rep.ship(_FakeFrame(encode_put(k, k.upper())))
    state: dict = {}
    for op, key, value in rep.replay_sink():
        state[key] = value if op == "put" else None
    assert {k: v for k, v in state.items() if v} == {"a": "A", "b": "B", "c": "C"}


def test_replay_excludes_unacked():
    """Frames beyond the acked prefix must not be replayed."""
    from kve.crc import encode_put

    rep, sink = _rep()
    for k in ("a", "b"):
        rep.ship(_FakeFrame(encode_put(k, k.upper())))
    # Simulate one more frame landing in the sink without advancing the ack.
    sink.append(encode_put("z", "ZZ"))
    replayed = list(rep.replay_sink())
    assert [k for _op, k, _v in replayed] == ["a", "b"]


def test_seq_mismatch_raises():
    class OffSink(MemorySink):
        def append(self, payload):
            n = super().append(payload)
            return n + 1  # lie about the sequence

    sink = OffSink()
    rep = Replicator(sink)
    with pytest.raises(ReplicationError):
        rep.ship(_FakeFrame(b"x"))


def test_stats_shape():
    rep, _sink = _rep()
    rep.ship(_FakeFrame(b"x"))
    stats = rep.stats()
    for key in ("shipped", "acked_seq", "sink_size", "in_flight"):
        assert key in stats


def test_failover_delete_visible():
    from kve.crc import encode_put, encode_delete

    rep, _sink = _rep()
    rep.ship(_FakeFrame(encode_put("a", "A")))
    rep.ship(_FakeFrame(encode_delete("a")))
    state: dict = {}
    for op, key, value in rep.replay_sink():
        if op == "put":
            state[key] = value
        else:
            state.pop(key, None)
    assert state == {}
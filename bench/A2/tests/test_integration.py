"""End-to-end: store + replication + compaction together, via the Client."""

from kve import Client
from kve.sink import MemorySink


def _client(tmp_path, **kw):
    return Client(tmp_path / "kv", replicate_to=MemorySink(), **kw)


def test_put_get_close(tmp_path):
    with _client(tmp_path) as kv:
        kv.put("hello", "world")
        assert kv.get("hello") == "world"


def test_replicated_state_matches_store(tmp_path):
    kv = _client(tmp_path)
    kv.put("a", "1")
    kv.put("b", "2")
    kv.put("a", "3")
    snapshot = kv.failover_snapshot()
    assert snapshot == {"a": "3", "b": "2"}
    kv.close()


def test_failover_snapshot_follows_deletes(tmp_path):
    kv = _client(tmp_path)
    kv.put("a", "1")
    kv.delete("a")
    assert kv.failover_snapshot() == {}
    kv.close()


def test_compact_then_read_local(tmp_path):
    kv = _client(tmp_path, flush_at=100)
    kv.put("k", "v1")
    kv.flush()
    kv.put("k", "v2")
    kv.flush()
    kv.compact()
    assert kv.get("k") == "v2"
    kv.close()


def test_full_cycle_compact_and_failover(tmp_path):
    """Writes -> flush -> overwrite -> compact -> failover: the standby's
    rebuilt state must equal the final values of every key."""
    kv = _client(tmp_path, flush_at=100)
    kv.put("a", "1")
    kv.put("b", "1")
    kv.flush()
    kv.put("a", "2")
    kv.put("c", "1")
    kv.flush()
    kv.compact()
    assert kv.get("a") == "2"
    assert kv.get("b") == "1"
    assert kv.get("c") == "1"
    snapshot = kv.failover_snapshot()
    assert snapshot == {"a": "2", "b": "1", "c": "1"}
    kv.close()


def test_compaction_reclaims_space(tmp_path):
    kv = _client(tmp_path, flush_at=100)
    for i in range(5):
        kv.put(f"k{i}", "v")
        kv.flush()
    before = kv.stats()["segments"]
    kv.compact()
    after = kv.stats()["segments"]
    assert before >= 5
    assert after == 1
    for i in range(5):
        assert kv.get(f"k{i}") == "v"
    kv.close()
"""KvStore read/write/flush/compaction integration (no replication)."""

from kve import KvStore


def _store(tmp_path, **kw):
    return KvStore(tmp_path / "store", **kw)


def test_put_get(tmp_path):
    kv = _store(tmp_path)
    kv.put("a", "1")
    assert kv.get("a") == "1"
    kv.close()


def test_delete_hides_value(tmp_path):
    kv = _store(tmp_path)
    kv.put("a", "1")
    kv.delete("a")
    assert kv.get("a") is None
    kv.close()


def test_get_absent(tmp_path):
    kv = _store(tmp_path)
    assert kv.get("nope") is None
    kv.close()


def test_flush_persists_value(tmp_path):
    kv = _store(tmp_path, flush_at=4)
    kv.put("a", "1")
    kv.flush()
    assert kv.get("a") == "1"
    kv.close()


def test_auto_flush_on_capacity(tmp_path):
    kv = _store(tmp_path, flush_at=2)
    kv.put("a", "1")
    kv.put("b", "2")  # triggers auto-flush (memtable full)
    assert kv.get("a") == "1"
    assert kv.get("b") == "2"
    kv.close()


def test_overwrite_survives_compaction(tmp_path):
    kv = _store(tmp_path, flush_at=100)
    kv.put("k", "v1")
    kv.flush()
    kv.put("k", "v2")
    kv.flush()
    kv.compact()
    assert kv.get("k") == "v2"
    kv.close()


def test_delete_survives_compaction(tmp_path):
    kv = _store(tmp_path, flush_at=100)
    kv.put("k", "v1")
    kv.flush()
    kv.delete("k")
    kv.flush()
    kv.compact()
    assert kv.get("k") is None
    kv.close()


def test_scan_range(tmp_path):
    kv = _store(tmp_path)
    for k in ["a", "b", "c", "d"]:
        kv.put(k, k.upper())
    assert list(kv.scan("b", "c")) == [("b", "B"), ("c", "C")]
    kv.close()


def test_scan_respects_overwrites(tmp_path):
    kv = _store(tmp_path, flush_at=2)
    kv.put("k", "old")
    kv.put("j", "x")
    kv.put("k", "new")
    assert list(kv.scan("k", "k")) == [("k", "new")]
    kv.close()


def test_stats_shape(tmp_path):
    kv = _store(tmp_path)
    kv.put("a", "1")
    kv.flush()
    stats = kv.stats()
    for key in ("put", "delete", "get", "flush", "compact", "memtable", "segments"):
        assert key in stats
    kv.close()


def test_closed_store_raises(tmp_path):
    kv = _store(tmp_path)
    kv.close()
    from kve import StoreClosedError

    try:
        kv.get("a")
        raise AssertionError("expected StoreClosedError")
    except StoreClosedError:
        pass


def test_invalid_key_rejected(tmp_path):
    from kve import KveError

    kv = _store(tmp_path)
    try:
        kv.put("", "x")
        raise AssertionError("expected KveError")
    except KveError:
        pass
    kv.close()
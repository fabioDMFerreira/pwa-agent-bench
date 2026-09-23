"""Unit tests: memtable and table semantics."""

from kve.memtable import MemTable
from kve.table import Table


def test_memtable_last_write_wins():
    m = MemTable()
    m.put("k", "1")
    m.put("k", "2")
    assert m.get("k") == (True, "2")
    assert len(m) == 1


def test_memtable_tombstone():
    m = MemTable()
    m.put("k", "1")
    m.delete("k")
    assert m.get("k") == (True, None)


def test_memtable_absent():
    m = MemTable()
    assert m.get("nope") == (False, None)


def test_flush_order_sorted():
    m = MemTable()
    for k in ["z", "a", "m"]:
        m.put(k, k.upper())
    assert [k for _op, k, _v in m.flush_order()] == ["a", "m", "z"]


def test_take_flush_empties():
    m = MemTable(max_entries=3)
    m.put("a", "1")
    m.put("b", "2")
    assert not m.is_full()
    items = m.take_flush()
    assert len(items) == 2
    assert len(m) == 0
    assert not m.is_full()


def test_is_full_boundary():
    m = MemTable(max_entries=2)
    m.put("a", "1")
    assert not m.is_full()
    m.put("b", "2")
    assert m.is_full()


def test_table_duplicate_collapse_last_wins():
    t = Table([("put", "k", "1"), ("put", "k", "2"), ("put", "j", "9")])
    found, value = t.get("k")
    assert found and value == "2"
    assert t.keys() == ["j", "k"]


def test_table_scan_range():
    t = Table([("put", "a", "1"), ("put", "c", "3"), ("put", "e", "5")])
    assert list(t.scan("b", "d")) == [("c", "3")]
    assert list(t.scan("a", "e")) == [("a", "1"), ("c", "3"), ("e", "5")]


def test_table_tombstone_hidden_from_scan():
    t = Table([("put", "a", "1"), ("delete", "a", None), ("put", "b", "2")])
    assert list(t.scan()) == [("b", "2")]
    assert t.tombstoned("a")


def test_table_stats():
    t = Table([("put", "a", "1"), ("delete", "a", None), ("put", "b", "2")])
    assert t.stats() == {"rows": 2, "live": 1, "tombstones": 1}
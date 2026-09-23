"""Immutable, sorted table — the in-memory mirror of a flushed segment.

A Table is built once (from a memtable flush) and never mutated; the store
keeps the newest tables first for the read path.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class _KV:
    key: str
    value: str | None  # None == tombstone


class Table:
    def __init__(self, entries):
        """Build from an iterable of (op, key, value). Duplicates collapse to
        the LAST occurrence (matches the semantics of an append log)."""
        collapsed: dict[str, _KV] = {}
        for op, key, value in entries:
            collapsed[key] = _KV(key=key, value=(None if op == "delete" else value))
        self._rows = tuple(sorted(collapsed.values(), key=lambda r: r.key))
        self._index = {r.key: r.value for r in self._rows}

    def __len__(self) -> int:
        return len(self._rows)

    def keys(self):
        return [r.key for r in self._rows]

    def get(self, key: str):
        """Returns (found, value) like MemTable.get."""
        if key not in self._index:
            return False, None
        return True, self._index[key]

    def scan(self, start_key: str | None = None, end_key: str | None = None):
        """Inclusive range scan over live entries (tombstones skipped)."""
        for row in self._rows:
            if start_key is not None and row.key < start_key:
                continue
            if end_key is not None and row.key > end_key:
                break
            if row.value is not None:
                yield row.key, row.value

    def tombstoned(self, key: str) -> bool:
        return self._index.get(key) is None and key in self._index

    def stats(self) -> dict:
        live = sum(1 for r in self._rows if r.value is not None)
        return {"rows": len(self._rows), "live": live, "tombstones": len(self._rows) - live}
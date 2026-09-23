"""The KvStore: memtable + segment files, with flush and compaction.

Read path: memtable first, then segments newest-first. Writes always go
through the memtable (and optionally a replicator hook), so a compacted
store and a not-yet-compacted store agree on every key.
"""

from pathlib import Path

from . import compaction, log
from .errors import KveError
from .lru import LruCache
from .memtable import MemTable
from .table import Table


class KvStore:
    def __init__(self, directory, flush_at: int = 16, hot_cache: int = 64):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.log = log.Log(self.dir / "wal")
        self.memtable = MemTable(max_entries=flush_at)
        self.flush_at = flush_at
        self._tables: list[Table] = []  # newest first
        self._cache = LruCache(hot_cache)
        self._closed = False
        self._replicator = None
        self._flush_counter = len(self.log.segments())
        self._ops = {"put": 0, "delete": 0, "get": 0, "flush": 0, "compact": 0}

    # -- replication hook ------------------------------------------------

    def attach_replicator(self, replicator) -> None:
        self._replicator = replicator
        self._replicator.bind_log(self.log)

    def _ship(self, frame) -> None:
        if self._replicator is not None:
            self._replicator.ship(frame)

    # -- writes ------------------------------------------------------------

    def put(self, key: str, value: str) -> None:
        self._check_open()
        if not isinstance(key, str) or not key:
            raise KveError("key must be a non-empty string")
        self.memtable.put(key, value)
        frame = self.log.append_put(key, value)
        self._ship(frame)
        self._ops["put"] += 1
        self._cache.invalidate(key)
        if self.memtable.is_full():
            self.flush()

    def delete(self, key: str) -> None:
        self._check_open()
        self.memtable.delete(key)
        frame = self.log.append_delete(key)
        self._ship(frame)
        self._ops["delete"] += 1
        self._cache.invalidate(key)
        if self.memtable.is_full():
            self.flush()

    # -- reads -------------------------------------------------------------

    def get(self, key: str):
        """Returns the live value or None (absent or tombstoned)."""
        self._check_open()
        self._ops["get"] += 1
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        found, value = self.memtable.get(key)
        if found:
            self._cache.put(key, value) if value is not None else None
            return value

        for table in self._tables:
            found, value = table.get(key)
            if found:
                if value is not None:
                    self._cache.put(key, value)
                return value
        return None

    def scan(self, start: str | None = None, end: str | None = None):
        """Merge-scan across memtable + tables (newest wins)."""
        merged: dict[str, str] = {}
        for table in self._tables:  # oldest applied first, newest last
            for k, v in table.scan(start, end):
                merged[k] = v
        for op, key, val in self.memtable.flush_order():
            if start is not None and key < start:
                continue
            if end is not None and key > end:
                continue
            if op == "put" and val is not None:
                merged[key] = val
            elif op == "delete":
                merged.pop(key, None)
        for k in sorted(merged):
            yield k, merged[k]

    # -- maintenance ---------------------------------------------------------

    def flush(self) -> None:
        """Write the memtable to a new segment and keep it as a Table."""
        if not self.memtable:
            return
        entries = self.memtable.take_flush()
        name = f"seg-{self._flush_counter:06d}.flush"
        path = self.dir / "tables" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        log.write_segment(path, entries)
        self._tables.insert(0, Table(entries))  # newest first
        self._flush_counter += 1
        self._ops["flush"] += 1

    def _table_segments(self) -> list[Path]:
        return sorted((self.dir / "tables").glob("seg-*.flush"), key=lambda p: p.stem)

    def compact(self) -> int:
        """Merge all flushed segments into one. Returns frames written."""
        self.flush()
        segs = self._table_segments()
        if len(segs) < 2:
            return 0
        out = self.dir / "tables" / f"seg-{self._flush_counter:06d}.flush"
        written = compaction.compact(segs, out)
        for old in segs:
            old.unlink()
        self._tables = [Table(self._readback(out))]
        self._flush_counter += 1
        self._ops["compact"] += 1
        return written

    def _readback(self, path: Path):
        from . import log as _log

        return _log.replay_segment(path)

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        self.flush()
        self.log.close()
        self._closed = True

    def _check_open(self) -> None:
        if self._closed:
            from .errors import StoreClosedError

            raise StoreClosedError("store is closed")

    def stats(self) -> dict:
        return {
            **self._ops,
            "memtable": self.memtable.stats(),
            "segments": len(self._table_segments()),
            "cache_size": len(self._cache),
        }
"""In-memory buffer that gets flushed to segments when it grows too large."""

from dataclasses import dataclass, field


@dataclass
class _Entry:
    value: object  # str for puts, None for tombstones


class MemTable:
    """Holds the most recent writes until flushed.

    Flush order is sorted by key (the on-disk table format is sorted); the
    in-memory map preserves last-write-wins per key, tombstones included.
    """

    def __init__(self, max_entries: int = 64):
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._max_entries = max_entries
        self._entries: dict[str, _Entry] = {}
        self._writes = 0

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def max_entries(self) -> int:
        return self._max_entries

    def put(self, key: str, value: str) -> None:
        self._entries[key] = _Entry(value)
        self._writes += 1

    def delete(self, key: str) -> None:
        # Tombstones are mandatory: older segments may still hold the key.
        self._entries[key] = _Entry(None)
        self._writes += 1

    def get(self, key: str):
        """Returns (found, value). found=False means absent from this table."""
        entry = self._entries.get(key)
        if entry is None:
            return False, None
        return True, entry.value

    def is_full(self) -> bool:
        return len(self._entries) >= self._max_entries

    def flush_order(self):
        """Yield (op, key, value) sorted by key — the order segments are written in."""
        for key in sorted(self._entries):
            entry = self._entries[key]
            if entry.value is None:
                yield "delete", key, None
            else:
                yield "put", key, entry.value

    def take_flush(self) -> list:
        """Pop everything for the caller and reset the table."""
        items = list(self.flush_order())
        self._entries.clear()
        return items

    def stats(self) -> dict:
        return {
            "entries": len(self._entries),
            "writes": self._writes,
            "tombstones": sum(1 for e in self._entries.values() if e.value is None),
        }
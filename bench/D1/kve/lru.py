"""Bounded LRU cache used by the store for hot-key lookups."""

from collections import OrderedDict


class LruCache:
    def __init__(self, capacity: int):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._capacity = capacity
        self._entries: "OrderedDict[object, object]" = OrderedDict()

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key, default=None):
        if key not in self._entries:
            return default
        self._entries.move_to_end(key)
        return self._entries[key]

    def put(self, key, value) -> None:
        self._entries[key] = value
        self._entries.move_to_end(key)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)

    def invalidate(self, key) -> None:
        self._entries.pop(key, None)

    def keys(self):
        return list(self._entries)
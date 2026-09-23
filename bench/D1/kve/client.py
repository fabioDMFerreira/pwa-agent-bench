"""High-level client: store + optional replication in one context manager."""

from pathlib import Path

from .replication import Replicator
from .sink import MemorySink
from .store import KvStore


class Client:
    """Owns a KvStore and (optionally) a replicator bound to it.

    Usage:
        with Client(directory) as kv:
            kv.put("a", "1")
            kv.get("a")
    """

    def __init__(self, directory, flush_at: int = 16, replicate_to=None):
        self.directory = Path(directory)
        self.store = KvStore(self.directory, flush_at=flush_at)
        self.replicator: Replicator | None = None
        if replicate_to is not None:
            self.replicator = Replicator(replicate_to)
            self.store.attach_replicator(self.replicator)

    # -- convenience facade -------------------------------------------------

    def put(self, key: str, value: str) -> None:
        self.store.put(key, value)

    def delete(self, key: str) -> None:
        self.store.delete(key)

    def get(self, key: str):
        return self.store.get(key)

    def flush(self) -> None:
        self.store.flush()

    def compact(self) -> int:
        return self.store.compact()

    def failover_snapshot(self) -> dict:
        """State a standby can rebuild from the replication sink:
        {key: value} over the durably acked prefix."""
        if self.replicator is None:
            raise RuntimeError("client was not created with a replication sink")
        state: dict[str, str] = {}
        for op, key, value in self.replicator.replay_sink():
            if op == "put":
                state[key] = value
            else:
                state.pop(key, None)
        return state

    # -- lifecycle ------------------------------------------------------------

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def stats(self) -> dict:
        return self.store.stats()

    # factory helpers ---------------------------------------------------------

    @classmethod
    def in_memory_replica(cls, directory, flush_at: int = 16):
        """Client replicating into a MemorySink (test/demo convenience)."""
        return cls(directory, flush_at=flush_at, replicate_to=MemorySink())
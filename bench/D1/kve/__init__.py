"""kve — a small embedded, file-backed key-value store.

Modules:
  log         append-only write-ahead log (segments of framed records)
  segment     segment frame iteration (key/value or tombstone entries)
  memtable    in-memory buffer flushed to segments
  table       immutable sorted table built from a flushed memtable
  compaction  merge of multiple segments (newest wins, tombstones dropped)
  store       the KvStore read/write path tying the above together
  replication log shipping to a sink with acknowledged offsets and failover
  sink        in-memory/file sinks used by replication and tests
"""

from .store import KvStore
from .replication import Replicator
from .sink import MemorySink, FileSink
from .client import Client
from .errors import (
    KveError,
    CorruptionError,
    NotFoundError,
    ReplicationError,
    StoreClosedError,
)

__all__ = [
    "KvStore",
    "Replicator",
    "MemorySink",
    "FileSink",
    "Client",
    "KveError",
    "CorruptionError",
    "NotFoundError",
    "ReplicationError",
    "StoreClosedError",
]

"""Tunables. Kept explicit (no env parsing) so tests can override per store."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    flush_at: int = 16          # memtable entries before auto-flush
    hot_cache: int = 64         # LRU entries for hot keys
    segment_bytes: int = 65536  # WAL rotation size (small for tests)
    compact_after_segments: int = 4
    replication_timeout_s: float = 30.0

    def validate(self) -> None:
        if self.flush_at < 1:
            raise ValueError("flush_at must be >= 1")
        if self.hot_cache < 1:
            raise ValueError("hot_cache must be >= 1")
        if self.segment_bytes < 64:
            raise ValueError("segment_bytes must be >= 64 (one frame minimum)")
        if self.compact_after_segments < 2:
            raise ValueError("compact_after_segments must be >= 2")


DEFAULT = Config()
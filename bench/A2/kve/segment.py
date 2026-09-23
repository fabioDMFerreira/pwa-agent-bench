"""Segment-level helpers (the "SSTable-ish" read side of a segment file).

Segments are append-only; compaction rewrites them. This module offers
read-only helpers used by the store's read path and by diagnostics.
"""

from pathlib import Path

from . import crc, log


def keys_in_segment(path: Path) -> list[str]:
    """All keys present in the segment, in first-occurrence order."""
    seen = []
    for op, key, _value in log.replay_segment(path):
        if key not in seen:
            seen.append(key)
    return seen


def latest_value(path: Path, key: str):
    """Value of `key` at the end of the segment (None if tombstoned there).

    Returns a `(found, value)` tuple so callers can distinguish "not in this
    segment" from "tombstoned in this segment".
    """
    found = False
    value = None
    for op, k, v in log.replay_segment(path):
        if k == key:
            found = True
            value = v
    return found, value


def count_entries(path: Path) -> int:
    return sum(1 for _ in log.replay_segment(path))


def segment_checksum(path: Path) -> int:
    """Stable checksum of a segment's logical content (order-sensitive)."""
    h = 0
    for op, key, value in log.replay_segment(path):
        h = (h * 31 + crc.frame_crc(
            (key + "|" + (value or "")).encode("utf-8"))) & 0xFFFFFFFF
    return h


def dump_segment(path: Path, limit: int = 50) -> str:
    """Human-readable dump (for CLI / debugging)."""
    lines = []
    for i, (op, key, value) in enumerate(log.replay_segment(path)):
        if i >= limit:
            lines.append(f"... ({count_entries(path)} total)")
            break
        if op == "put":
            lines.append(f"{i:4d}  PUT  {key} = {value}")
        else:
            lines.append(f"{i:4d}  DEL  {key}")
    return "\n".join(lines)
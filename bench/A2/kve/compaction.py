"""Segment compaction: merge multiple segments into one.

Rules (see TASK.md / spec):
  * When the same key appears in several segments, the entry from the
    NEWEST segment wins (segments are ordered oldest -> newest by their
    numeric suffix).
  * Tombstones propagate: a delete in a newer segment hides all older
    values of that key.
  * A tombstone that ends up as the final word for a key is DROPPED from
    the output (there is nothing left to hide).
"""

from pathlib import Path

from . import log, segment


def compact(segment_paths, out_path: Path) -> int:
    """Merge `segment_paths` into a single new segment at `out_path`.

    `segment_paths` is expected in ascending (oldest-first) order, as
    returned by `Log.segments()`. Returns the number of frames written to
    the output (tombstones excluded).
    """
    survivors: dict[str, str | None] = {}
    # Oldest first: later (newer) entries overwrite earlier ones, and the
    # final word for each key is whatever the newest segment says.
    for path in segment_paths:
        for op, key, value in log.replay_segment(Path(path)):
            survivors[key] = None if op == "delete" else value

    entries = [
        ("put", key, value)
        for key, value in survivors.items()
        if value is not None
    ]
    entries.sort(key=lambda e: e[1])
    written = log.write_segment(Path(out_path), entries)
    return written


def compact_size_estimate(segment_paths) -> int:
    """Pre-compaction estimate: output frames <= sum of unique keys across
    all inputs (tombstones removed). Used for space-reclamation decisions."""
    unique: set[str] = set()
    for path in segment_paths:
        unique.update(segment.keys_in_segment(Path(path)))
    return len(unique)


def needs_compaction(segment_paths, threshold: int = 4) -> bool:
    """Heuristic: too many small segments is the main space leak."""
    if len(list(segment_paths)) < threshold:
        return False
    total = sum(Path(p).stat().st_size for p in segment_paths)
    return total > 0